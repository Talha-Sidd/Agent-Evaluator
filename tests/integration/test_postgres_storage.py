"""Runs only with an explicit disposable ARL_TEST_DATABASE_URL."""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from agent_reliability_lab.api.app import RunService, create_app
from agent_reliability_lab.platform.storage.postgres import (
    MigrationError,
    PostgresRunRepository,
)

DSN = os.environ.get("ARL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable PostgreSQL test URL not configured")
TOKEN = "a" * 32
OTHER = "b" * 32


@pytest.fixture(autouse=True)
def require_disposable_database() -> None:
    assert DSN is not None
    assert os.environ.get("ARL_ALLOW_TEST_DB_RESET") == "1"
    assert conninfo_to_dict(DSN).get("dbname", "").endswith("_test")


def test_migration_restart_ownership_and_trace() -> None:
    assert DSN is not None
    repository = PostgresRunRepository(DSN)
    repository.migrate()
    repository.migrate()
    with psycopg.connect(DSN) as connection:
        connection.execute("TRUNCATE stored_runs CASCADE")
    first = TestClient(create_app(
        RunService(repository=repository), api_tokens={TOKEN: "alice", OTHER: "bob"}
    ))
    payload = {
        "scenario_id": "pg-case", "task": "needle",
        "repository_files": {"file.txt": "needle"}, "expected_behavior": "find file",
        "expected_tools": ["repo_search"], "expected_matching_files": ["file.txt"],
    }
    created = first.post("/runs", json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    second = TestClient(create_app(
        RunService(repository=PostgresRunRepository(DSN)),
        api_tokens={TOKEN: "alice", OTHER: "bob"},
    ))
    path = f"/runs/{run_id}"
    assert second.get(path, headers={"Authorization": f"Bearer {OTHER}"}).status_code == 404
    assert second.get(path, headers={"Authorization": f"Bearer {TOKEN}"}).json() == created.json()
    evaluation = second.get(path + "/evaluation", headers={
        "Authorization": f"Bearer {TOKEN}"
    })
    assert evaluation.status_code == 200
    assert evaluation.json()["passed"]
    with psycopg.connect(DSN) as connection:
        row = connection.execute(
            "SELECT count(*) FROM stored_trace_events WHERE run_id = %s", (run_id,)
        ).fetchone()
        assert row is not None and row[0] == len(created.json()["trace"])
        persisted = connection.execute(
            "SELECT owner, agent_version, evaluator_version FROM stored_runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        assert persisted == ("alice", "repopilot-demo-v1", "starter-v2")
        connection.execute("TRUNCATE stored_runs CASCADE")


def test_postgres_retention_and_expiry() -> None:
    assert DSN is not None
    repository = PostgresRunRepository(DSN)
    repository.migrate()
    with psycopg.connect(DSN) as connection:
        connection.execute("TRUNCATE stored_runs CASCADE")
    api = TestClient(create_app(
        RunService(repository=repository, max_runs=1), api_tokens={TOKEN: "alice"}
    ))
    payload = {"scenario_id": "retention", "task": "needle", "expected_behavior": "find"}
    headers = {"Authorization": f"Bearer {TOKEN}"}
    first = api.post("/runs", json=payload, headers=headers)
    second = api.post("/runs", json=payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert api.get(f"/runs/{first.json()['run_id']}", headers=headers).status_code == 404
    current = second.json()["run_id"]
    with psycopg.connect(DSN) as connection:
        connection.execute(
            "UPDATE stored_runs SET expires_at = now() - interval '1 second' WHERE run_id = %s",
            (current,),
        )
    assert api.get(f"/runs/{current}", headers=headers).status_code == 404
    with psycopg.connect(DSN) as connection:
        assert connection.execute(
            "SELECT count(*) FROM stored_runs WHERE run_id = %s", (current,)
        ).fetchone() == (0,)
    assert api.post("/runs", json=payload, headers=headers).status_code == 201
    with psycopg.connect(DSN) as connection:
        assert connection.execute(
            "SELECT count(*) FROM stored_runs"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM stored_trace_events WHERE run_id = %s", (current,)
        ).fetchone() == (0,)
        connection.execute("TRUNCATE stored_runs CASCADE")


def test_unknown_migration_fails_closed() -> None:
    assert DSN is not None
    repository = PostgresRunRepository(DSN)
    repository.migrate()
    with psycopg.connect(DSN) as connection:
        connection.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (999, %s)",
            ("0" * 64,),
        )
    try:
        with pytest.raises(MigrationError):
            repository.migrate()
    finally:
        with psycopg.connect(DSN) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = 999")
