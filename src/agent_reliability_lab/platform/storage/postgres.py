"""Transactional PostgreSQL storage with explicit versioned migrations."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from agent_reliability_lab.domain.models import AgentResult, EvaluationResult, StoredRun, TraceEvent

_MIGRATIONS = Path(__file__).with_name("migrations")
_LOCK_ID = 0x41524C31
SCHEMA_VERSION = 1


class StorageError(Exception):
    """Database operation failed; details stay out of API responses."""


class StorageLimitError(StorageError):
    """A single record exceeds configured retention capacity."""


class MigrationError(StorageError):
    """Schema is missing, newer, or differs from a reviewed migration."""


class PostgresRunRepository:
    """One transaction per operation; safe across processes and restarts."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("PostgreSQL DSN is required")
        self._dsn = dsn

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=5)

    def migrate(self) -> None:
        """Apply reviewed SQL files exactly once and reject drift."""
        try:
            with self._connect() as connection:
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version integer PRIMARY KEY, checksum text NOT NULL, "
                    "applied_at timestamptz NOT NULL DEFAULT now())"
                )
                found = {
                    cast(int, row[0]): cast(str, row[1])
                    for row in connection.execute(
                        "SELECT version, checksum FROM schema_migrations"
                    ).fetchall()
                }
                files = sorted(_MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
                versions = [int(path.name[:3]) for path in files]
                if versions != list(range(1, SCHEMA_VERSION + 1)):
                    raise MigrationError("reviewed migration files are missing or duplicated")
                known = {int(path.name[:3]) for path in files}
                if set(found) - known:
                    raise MigrationError("database has unknown migrations")
                for path in files:
                    version = int(path.name[:3])
                    source = path.read_bytes()
                    checksum = hashlib.sha256(source).hexdigest()
                    if version in found:
                        if found[version] != checksum:
                            raise MigrationError("migration checksum differs")
                        continue
                    for statement in source.decode("utf-8").split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (version, checksum),
                    )
        except psycopg.Error as exc:
            raise StorageError("database migration failed") from exc

    def _require_schema(self, connection: psycopg.Connection[tuple[object, ...]]) -> None:
        version = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()
        if version is None or version[0] != SCHEMA_VERSION:
            raise MigrationError("database migration required")

    def save(self, record: StoredRun, *, max_runs: int, max_bytes: int) -> None:
        """Save result, evaluation, and ordered trace in one transaction."""
        record = StoredRun.model_validate(record.model_dump())
        result_value = record.result.model_dump(mode="json", exclude={"trace"})
        evaluation_value = record.evaluation.model_dump(mode="json")
        events = [event.model_dump(mode="json") for event in record.result.trace]
        size = sum(
            len(json.dumps(value, separators=(",", ":")).encode("utf-8"))
            for value in (result_value, evaluation_value, *events)
        )
        if size > max_bytes:
            raise StorageLimitError("record exceeds retention capacity")
        try:
            with self._connect() as connection:
                self._require_schema(connection)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
                connection.execute("DELETE FROM stored_runs WHERE expires_at <= now()")
                totals = connection.execute(
                    "SELECT count(*), coalesce(sum(size_bytes), 0) FROM stored_runs"
                ).fetchone()
                assert totals is not None
                count, used = cast(int, totals[0]), cast(int, totals[1])
                while count >= max_runs or used + size > max_bytes:
                    removed = connection.execute(
                        "DELETE FROM stored_runs WHERE run_id = ("
                        "SELECT run_id FROM stored_runs ORDER BY created_at, run_id LIMIT 1) "
                        "RETURNING size_bytes"
                    ).fetchone()
                    if removed is None:
                        raise StorageLimitError("retention capacity unavailable")
                    count -= 1
                    used -= cast(int, removed[0])
                connection.execute(
                    "INSERT INTO stored_runs (run_id, owner, scenario_id, result_json, "
                    "evaluation_json, agent_version, evaluator_version, created_at, "
                    "expires_at, size_bytes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (record.result.run_id, record.owner, record.result.scenario_id,
                     Jsonb(result_value), Jsonb(evaluation_value), record.agent_version,
                     record.evaluator_version, record.created_at, record.expires_at, size),
                )
                for ordinal, event in enumerate(record.result.trace):
                    connection.execute(
                        "INSERT INTO stored_trace_events (event_id, run_id, ordinal, event_json) "
                        "VALUES (%s, %s, %s, %s)",
                        (event.event_id, record.result.run_id, ordinal, Jsonb(events[ordinal])),
                    )
        except psycopg.Error as exc:
            raise StorageError("database write failed") from exc

    def get(self, run_id: UUID, owner: str) -> StoredRun | None:
        try:
            with self._connect() as connection:
                self._require_schema(connection)
                connection.execute("DELETE FROM stored_runs WHERE expires_at <= now()")
                row = connection.execute(
                    "SELECT owner, result_json, evaluation_json, agent_version, "
                    "evaluator_version, created_at, expires_at FROM stored_runs "
                    "WHERE run_id = %s AND owner = %s AND expires_at > now() FOR SHARE",
                    (run_id, owner),
                ).fetchone()
                if row is None:
                    return None
                trace = connection.execute(
                    "SELECT event_json FROM stored_trace_events WHERE run_id = %s "
                    "ORDER BY ordinal", (run_id,),
                ).fetchall()
                result = AgentResult.model_validate(row[1])
                result.trace = [TraceEvent.model_validate(event[0]) for event in trace]
                if result.run_id != run_id or any(event.run_id != run_id for event in result.trace):
                    raise StorageError("stored evidence identity mismatch")
                return StoredRun(
                    owner=str(row[0]), result=result,
                    evaluation=EvaluationResult.model_validate(row[2]),
                    agent_version=str(row[3]), evaluator_version=str(row[4]),
                    created_at=cast(datetime, row[5]), expires_at=cast(datetime, row[6]),
                )
        except psycopg.Error as exc:
            raise StorageError("database read failed") from exc
        except ValidationError as exc:
            raise StorageError("stored evidence invalid") from exc
