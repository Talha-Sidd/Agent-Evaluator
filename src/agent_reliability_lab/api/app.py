"""Authenticated, bounded API around the deterministic platform."""

import asyncio
import json
import math
import os
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from threading import BoundedSemaphore, Lock
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import AgentResult, Scenario
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.security import public_result


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
    ) -> None:
        if (
            not math.isfinite(ttl_seconds)
            or min(max_runs, ttl_seconds, max_bytes, concurrency) <= 0
        ):
            raise ValueError("run service limits must be positive")
        self._runner = runner or ScenarioRunner()
        self._agent = RepoPilotDemo()
        self._runs: OrderedDict[UUID, tuple[str, float, AgentResult, int]] = OrderedDict()
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
                self._bytes -= size

    def create_run(self, scenario: Scenario, owner: str) -> AgentResult:
        if not self._slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="run capacity reached")
        try:
            result = public_result(self._runner.run(self._agent, scenario))
            size = len(result.model_dump_json().encode())
            if size > min(self._max_bytes, 1024 * 1024):
                raise HTTPException(status_code=413, detail="result exceeds retention limit")
            with self._lock:
                self._expire()
                while self._runs and (
                    len(self._runs) >= self._max_runs or self._bytes + size > self._max_bytes
                ):
                    _, (_, _, _, removed_size) = self._runs.popitem(last=False)
                    self._bytes -= removed_size
                self._runs[result.run_id] = (owner, self._clock() + self._ttl, result, size)
                self._bytes += size
            return result.model_copy(deep=True)
        finally:
            self._slots.release()

    def get_run(self, run_id: UUID, owner: str) -> AgentResult | None:
        with self._lock:
            self._expire()
            stored = self._runs.get(run_id)
            if stored is None or stored[0] != owner:
                return None
            return stored[2].model_copy(deep=True)


def create_app(
    service: RunService | None = None,
    *,
    api_tokens: Mapping[str, str] | None = None,
) -> FastAPI:
    run_service = service or RunService()
    if api_tokens is None:
        try:
            value: Any = json.loads(os.environ.get("ARL_API_TOKENS", "{}"))
        except ValueError:
            raise ValueError("invalid ARL_API_TOKENS configuration") from None
    else:
        value = dict(api_tokens)
    if not isinstance(value, dict) or any(
        not isinstance(token, str) or len(token) < 32 or not isinstance(owner, str) or not owner
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

    return app


app = create_app()
