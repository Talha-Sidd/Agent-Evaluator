"""Harness-owned dispatch, evidence, identities, budgets, and worker lifecycles."""

import time
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_reliability_lab.domain.errors import ToolExecutionError
from agent_reliability_lab.domain.models import (
    AgentResult,
    AgentTask,
    ErrorCode,
    PermissionDecision,
    RiskLevel,
    RunStatus,
    RunTiming,
    Scenario,
    ToolCall,
    TraceEvent,
)
from agent_reliability_lab.domain.protocols import AgentAdapter
from agent_reliability_lab.platform.security import fingerprint, sanitize
from agent_reliability_lab.platform.tools.registry import TypedToolRegistry
from agent_reliability_lab.platform.tools.repopilot import build_repopilot_registry
from agent_reliability_lab.platform.workers import (
    Connection,
    receive_json,
    send_json,
    start_worker,
    stop_worker,
)


class ToolRequest(BaseModel):
    """Strict IPC message sent by an agent worker to request one tool call."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["tool"]
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]


class RemoteTools:
    """Agent-side proxy that forwards tool requests to the parent runner."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        send_json(self._connection, {"kind": "tool", "name": name, "arguments": arguments})
        response = receive_json(self._connection)
        if "error" in response:
            raise ToolExecutionError(ErrorCode(response["error"]))
        output = response["output"]
        if not isinstance(output, dict):
            raise ToolExecutionError(ErrorCode.INVALID_TOOL_OUTPUT)
        return output


def _agent_worker(
    connection: Connection,
    agent: AgentAdapter,
    task: AgentTask,
    run_id: UUID,
) -> None:
    try:
        send_json(connection, {"kind": "ready"})
        result = agent.run(task, run_id, RemoteTools(connection))
        send_json(connection, {"kind": "result", "result": result.model_dump(mode="json")})
    except ToolExecutionError as exc:
        send_json(connection, {"kind": "error", "error": exc.code})
    except Exception:  # noqa: BLE001 -- adapter boundary preserves failures without payload leaks
        send_json(connection, {"kind": "error", "error": ErrorCode.INTERNAL_ERROR})
    finally:
        connection.close()


class CallObserver:
    """Translate registry callbacks into harness-owned records and trace events."""

    def __init__(self, run_id: UUID, call: ToolCall, events: list[TraceEvent]) -> None:
        self.run_id, self.call, self.events = run_id, call, events

    def emit(
        self,
        event_type: str,
        success: bool | None = None,
        code: ErrorCode | None = None,
    ) -> None:
        self.events.append(
            TraceEvent(
                run_id=self.run_id,
                call_id=self.call.call_id,
                tool_name=self.call.name,
                event_type=event_type,
                success=success,
                error_code=code,
            )
        )

    def validated(self, arguments: dict[str, Any]) -> None:
        self.call.arguments = sanitize(arguments)
        self.call.arguments_sha256 = fingerprint(arguments)

    def permission(self, decision: PermissionDecision, risk: RiskLevel) -> None:
        self.call.permission_allowed = decision.allowed
        self.call.requires_approval = decision.requires_approval
        self.call.risk = risk
        self.emit("permission.checked", decision.allowed)

    def started(self) -> None:
        self.call.executed = True
        self.emit("tool.started")

    def worker_ready(self, startup_ms: float) -> None:
        self.call.worker_startup_ms = startup_ms


class ScenarioRunner:
    """Own run identity, budgets, worker lifecycles, permissions, and terminal events."""

    def __init__(self, registry: TypedToolRegistry | None = None) -> None:
        self._registry = registry or build_repopilot_registry()

    def safety_controls(self) -> dict[str, bool]:
        from agent_reliability_lab.platform.evals.safety import permission_controls

        return permission_controls(self._registry.permission_policy)

    def run(self, agent: AgentAdapter, scenario: Scenario) -> AgentResult:
        run_started = time.monotonic()
        agent_startup_ms: float | None = None
        run_id = uuid4()
        events = [
            TraceEvent(run_id=run_id, event_type="run.started"),
            TraceEvent(run_id=run_id, event_type="agent.started"),
        ]
        calls: list[ToolCall] = []
        result: AgentResult
        try:
            # Revalidate mutable caller-owned models and retain validation failures.
            try:
                scenario = Scenario.model_validate(scenario.model_dump())
            except ValidationError:
                raise ToolExecutionError(ErrorCode.INVALID_INPUT) from None
            deadline = time.monotonic() + scenario.timeout_seconds
            agent_start = time.monotonic()
            process, connection = start_worker(_agent_worker, agent, scenario.agent_task(), run_id)
            worker_ready = False
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not connection.poll(remaining):
                        raise ToolExecutionError(ErrorCode.TIMEOUT)
                    message = receive_json(connection)
                    if message.get("kind") == "ready":
                        if worker_ready or message != {"kind": "ready"}:
                            raise ToolExecutionError(ErrorCode.INTERNAL_ERROR)
                        worker_ready = True
                        agent_startup_ms = (time.monotonic() - agent_start) * 1000
                        continue
                    if not worker_ready:
                        raise ToolExecutionError(ErrorCode.INTERNAL_ERROR)
                    if message.get("kind") == "error":
                        raise ToolExecutionError(ErrorCode(message["error"]))
                    if message.get("kind") == "result":
                        result = AgentResult.model_validate(message["result"])
                        if result.run_id != run_id or result.scenario_id != scenario.scenario_id:
                            raise ToolExecutionError(ErrorCode.INTERNAL_ERROR)
                        break
                    try:
                        request = ToolRequest.model_validate(message)
                    except ValidationError:
                        raise ToolExecutionError(ErrorCode.INVALID_TOOL_ARGUMENTS) from None
                    call_started = time.monotonic()
                    call = ToolCall(name=sanitize(request.name), success=False)
                    calls.append(call)
                    observer = CallObserver(run_id, call, events)
                    observer.emit("tool.requested")
                    try:
                        if len(calls) > scenario.max_steps:
                            raise ToolExecutionError(ErrorCode.STEP_LIMIT_EXCEEDED)
                        output = self._registry.execute(
                            request.name,
                            request.arguments,
                            observer=observer,
                            deadline=deadline,
                        ).model_dump(mode="json")
                        call.output = sanitize(output)
                        call.output_sha256 = fingerprint(output)
                        call.success = True
                        observer.emit("tool.completed", True)
                        send_json(connection, {"output": output})
                    except ToolExecutionError as exc:
                        call.error_code = exc.code
                        observer.emit("tool.failed", False, exc.code)
                        if exc.code in {ErrorCode.TIMEOUT, ErrorCode.STEP_LIMIT_EXCEEDED}:
                            raise
                        send_json(connection, {"error": exc.code})
                    finally:
                        call.request_duration_ms = (time.monotonic() - call_started) * 1000
            finally:
                stop_worker(process, connection)
        except ToolExecutionError as exc:
            result = AgentResult(
                run_id=run_id,
                scenario_id=scenario.scenario_id,
                status=RunStatus.FAILED,
                final_answer="Run failed.",
                error=exc.code.value,
                error_code=exc.code,
            )
        except Exception:  # noqa: BLE001 -- always finalize a failed harness lifecycle
            result = AgentResult(
                run_id=run_id,
                scenario_id=scenario.scenario_id,
                status=RunStatus.FAILED,
                final_answer="Run failed.",
                error=ErrorCode.INTERNAL_ERROR.value,
                error_code=ErrorCode.INTERNAL_ERROR,
            )
        if result.status is RunStatus.FAILED and result.error_code is None:
            result.error_code = ErrorCode.INTERNAL_ERROR
        if result.error_code is not None:
            result.status = RunStatus.FAILED
        # Free-form adapter error text and self-reported calls/traces are not evidence.
        result.error = result.error_code.value if result.error_code else None
        result.final_answer = sanitize(result.final_answer)
        result.tool_calls = calls
        success = result.status is RunStatus.SUCCEEDED
        events.extend(
            [
                TraceEvent(
                    run_id=run_id,
                    event_type="agent.completed",
                    success=success,
                    error_code=result.error_code,
                ),
                TraceEvent(
                    run_id=run_id,
                    event_type="run.completed",
                    success=success,
                    error_code=result.error_code,
                ),
            ]
        )
        result.trace = events
        result.timing = RunTiming(
            run_duration_ms=(time.monotonic() - run_started) * 1000,
            agent_worker_startup_ms=agent_startup_ms,
        )
        return result
