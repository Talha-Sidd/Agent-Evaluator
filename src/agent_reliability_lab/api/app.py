"""Authenticated, bounded API around the deterministic platform."""

import asyncio
import json
import math
import os
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore, Lock
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import AgentResult, EvaluationResult, Scenario, StoredRun
from agent_reliability_lab.domain.protocols import RunRepository
from agent_reliability_lab.platform.evals.comparison import EVALUATOR_VERSION
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.security import public_result
from agent_reliability_lab.platform.storage.postgres import (
    PostgresRunRepository,
    StorageError,
    StorageLimitError,
)

AGENT_VERSION = "repopilot-demo-v1"


class BodyLimitMiddleware:
    """Reject oversized or slow request bodies before application processing."""

    def __init__(self, app: ASGIApp, limit: int = 2 * 1024 * 1024) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        content_length = dict(scope["headers"]).get(b"content-length")
        if content_length:
            try:
                too_large = int(content_length) > self.limit
            except ValueError:
                await JSONResponse({"detail": "invalid content length"}, status_code=400)(
                    scope, receive, send
                )
                return
            if too_large:
                await JSONResponse({"detail": "request too large"}, status_code=413)(
                    scope, receive, send
                )
                return
        body = bytearray()
        deadline = time.monotonic() + 10
        while True:
            try:
                message = await asyncio.wait_for(receive(), max(0, deadline - time.monotonic()))
            except TimeoutError:
                await JSONResponse({"detail": "request body timeout"}, status_code=408)(
                    scope, receive, send
                )
                return
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                await JSONResponse({"detail": "request too large"}, status_code=413)(
                    scope, receive, send
                )
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class RunService:
    """Own authenticated run execution, bounded retention, expiry, and concurrency."""

    def __init__(
        self,
        *,
        max_runs: int = 100,
        ttl_seconds: float = 300,
        max_bytes: int = 8 * 1024 * 1024,
        concurrency: int = 2,
        clock: Callable[[], float] = time.monotonic,
        runner: ScenarioRunner | None = None,
        repository: RunRepository | None = None,
    ) -> None:
        if (
            not math.isfinite(ttl_seconds)
            or min(max_runs, ttl_seconds, max_bytes, concurrency) <= 0
        ):
            raise ValueError("run service limits must be positive")
        self._runner = runner or ScenarioRunner()
        self._agent = RepoPilotDemo()
        self._evaluator = StarterEvaluator()
        self._repository = repository
        self._runs: OrderedDict[UUID, tuple[str, float, AgentResult, int]] = OrderedDict()
        self._evaluations: dict[UUID, EvaluationResult] = {}
        self._max_runs, self._ttl, self._max_bytes = max_runs, ttl_seconds, max_bytes
        self._clock = clock
        self._bytes = 0
        self._lock = Lock()
        self._slots = BoundedSemaphore(concurrency)

    def _expire(self) -> None:
        now = self._clock()
        for run_id, (_, expires, _, size) in list(self._runs.items()):
            if expires <= now:
                del self._runs[run_id]
                self._evaluations.pop(run_id, None)
                self._bytes -= size

    def create_run(self, scenario: Scenario, owner: str) -> AgentResult:
        if not self._slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="run capacity reached")
        try:
            raw_result = self._runner.run(self._agent, scenario)
            evaluation = self._evaluator.evaluate(scenario, raw_result)
            result = public_result(raw_result)
            size = len(result.model_dump_json().encode())
            if size > min(self._max_bytes, 1024 * 1024):
                raise HTTPException(status_code=413, detail="result exceeds retention limit")
            if self._repository is not None:
                now = datetime.now(UTC)
                record = StoredRun(
                    owner=owner, result=result, evaluation=evaluation,
                    agent_version=AGENT_VERSION, evaluator_version=EVALUATOR_VERSION,
                    created_at=now, expires_at=now + timedelta(seconds=self._ttl),
                )
                try:
                    self._repository.save(record, max_runs=self._max_runs, max_bytes=self._max_bytes)
                except StorageLimitError:
                    raise HTTPException(status_code=413, detail="result exceeds retention limit") from None
                except StorageError:
                    raise HTTPException(status_code=503, detail="run storage unavailable") from None
                return result.model_copy(deep=True)
            with self._lock:
                self._expire()
                while self._runs and (
                    len(self._runs) >= self._max_runs or self._bytes + size > self._max_bytes
                ):
                    removed_id, (_, _, _, removed_size) = self._runs.popitem(last=False)
                    self._evaluations.pop(removed_id, None)
                    self._bytes -= removed_size
                self._runs[result.run_id] = (owner, self._clock() + self._ttl, result, size)
                self._evaluations[result.run_id] = evaluation
                self._bytes += size
            return result.model_copy(deep=True)
        finally:
            self._slots.release()

    def get_run(self, run_id: UUID, owner: str) -> AgentResult | None:
        if self._repository is not None:
            try:
                record = self._repository.get(run_id, owner)
            except StorageError:
                raise HTTPException(status_code=503, detail="run storage unavailable") from None
            return record.result.model_copy(deep=True) if record is not None else None
        with self._lock:
            self._expire()
            stored = self._runs.get(run_id)
            if stored is None or stored[0] != owner:
                return None
            return stored[2].model_copy(deep=True)

    def get_evaluation(self, run_id: UUID, owner: str) -> EvaluationResult | None:
        if self._repository is not None:
            try:
                record = self._repository.get(run_id, owner)
            except StorageError:
                raise HTTPException(status_code=503, detail="run storage unavailable") from None
            return record.evaluation.model_copy(deep=True) if record is not None else None
        with self._lock:
            self._expire()
            stored = self._runs.get(run_id)
            if stored is None or stored[0] != owner:
                return None
            return self._evaluations[run_id].model_copy(deep=True)


def create_app(
    service: RunService | None = None,
    *,
    api_tokens: Mapping[str, str] | None = None,
) -> FastAPI:
    run_service = service or RunService(
        repository=PostgresRunRepository(os.environ["ARL_DATABASE_URL"])
        if os.environ.get("ARL_DATABASE_URL") else None
    )
    if api_tokens is None:
        try:
            value: Any = json.loads(os.environ.get("ARL_API_TOKENS", "{}"))
        except ValueError:
            raise ValueError("invalid ARL_API_TOKENS configuration") from None
    else:
        value = dict(api_tokens)
    if not isinstance(value, dict) or any(
        not isinstance(token, str) or len(token) < 32 or not isinstance(owner, str)
        or not owner or len(owner) > 256
        for token, owner in value.items()
    ):
        raise ValueError("API tokens must be at least 32 characters and map to nonempty owners")
    tokens: dict[str, str] = value
    app = FastAPI(title="Agent Reliability Lab", version="0.1.0")
    app.add_middleware(BodyLimitMiddleware)

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> str:
        if not tokens:
            raise HTTPException(status_code=503, detail="run API authentication is not configured")
        candidate = (authorization or "").removeprefix("Bearer ")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="authentication required")
        for token, owner in tokens.items():
            if secrets.compare_digest(candidate.encode(), token.encode()):
                return owner
        raise HTTPException(status_code=401, detail="invalid credentials")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default errors can include rejected inputs.
        return JSONResponse(status_code=422, content={"detail": "invalid request"})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs", response_model=AgentResult, status_code=status.HTTP_201_CREATED)
    def create_run(scenario: Scenario, owner: Annotated[str, Depends(authenticate)]) -> AgentResult:
        return run_service.create_run(scenario, owner)

    @app.get("/runs/{run_id}", response_model=AgentResult)
    def get_run(run_id: UUID, owner: Annotated[str, Depends(authenticate)]) -> AgentResult:
        result = run_service.get_run(run_id, owner)
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.get("/runs/{run_id}/evaluation", response_model=EvaluationResult)
    def get_evaluation(
        run_id: UUID, owner: Annotated[str, Depends(authenticate)]
    ) -> EvaluationResult:
        evaluation = run_service.get_evaluation(run_id, owner)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="run not found")
        return evaluation

    return app


app = create_app()
