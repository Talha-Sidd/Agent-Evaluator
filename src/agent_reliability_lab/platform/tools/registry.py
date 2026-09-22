"""Validate, authorize, supervise, and observe each tool dispatch."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

from agent_reliability_lab.domain.errors import ToolExecutionError
from agent_reliability_lab.domain.models import ErrorCode, PermissionDecision, RiskLevel, ToolAction
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.workers import (
    Connection,
    receive_json,
    send_json,
    start_worker,
    stop_worker,
)

__all__ = ["ApprovalRequired", "ToolDefinition", "ToolExecutionError", "TypedToolRegistry"]


class ApprovalRequired(ToolExecutionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(ErrorCode.APPROVAL_REQUIRED)
        self.decision = decision


class DispatchObserver(Protocol):
    def validated(self, arguments: dict[str, Any]) -> None: ...
    def permission(self, decision: PermissionDecision, risk: RiskLevel) -> None: ...
    def started(self) -> None: ...


@dataclass(frozen=True)
class ToolDefinition[InputModel: BaseModel, OutputModel: BaseModel]:
    name: str
    risk: RiskLevel
    input_model: type[InputModel]
    output_model: type[OutputModel]
    handler: Callable[[InputModel], OutputModel]
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.name or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("tool name and finite positive timeout are required")


def _tool_worker(
    connection: Connection,
    tool: ToolDefinition[Any, Any],
    arguments: dict[str, Any],
) -> None:
    try:
        output = tool.handler(tool.input_model.model_validate(arguments))
        raw = (
            output.model_dump(mode="python", warnings=False)
            if isinstance(output, BaseModel)
            else output
        )
        try:
            validated = tool.output_model.model_validate(raw, strict=True)
            encoded = validated.model_dump_json(warnings=False)
            if len(encoded.encode()) > 131072:
                raise ValueError("output too large")
        except (ValidationError, ValueError, TypeError):
            send_json(connection, {"error": ErrorCode.INVALID_TOOL_OUTPUT})
            return
        send_json(connection, {"output": validated.model_dump(mode="json", warnings=False)})
    except Exception:  # noqa: BLE001 -- worker boundary normalizes arbitrary handler failures
        send_json(connection, {"error": ErrorCode.TOOL_ERROR})
    finally:
        connection.close()


class TypedToolRegistry:
    def __init__(self, permission_policy: DeterministicPermissionPolicy) -> None:
        self._permission_policy = permission_policy
        self._tools: dict[str, ToolDefinition[Any, Any]] = {}

    def register[I: BaseModel, O: BaseModel](self, tool: ToolDefinition[I, O]) -> None:
        if tool.name in self._tools:
            raise ValueError("tool already registered")
        self._tools[tool.name] = tool

    @property
    def permission_policy(self) -> DeterministicPermissionPolicy:
        return self._permission_policy

    def get(self, name: str) -> ToolDefinition[Any, Any]:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolExecutionError(ErrorCode.TOOL_NOT_FOUND) from None

    def check_permission(self, name: str) -> PermissionDecision:
        tool = self.get(name)
        return self._permission_policy.check(ToolAction(tool_name=tool.name, risk=tool.risk))

    def execute(
        self,
        name: str,
        arguments: object,
        *,
        observer: DispatchObserver | None = None,
        deadline: float | None = None,
    ) -> BaseModel:
        tool = self.get(name)
        try:
            raw = (
                arguments.model_dump(warnings=False)
                if isinstance(arguments, BaseModel)
                else arguments
            )
            typed_input = tool.input_model.model_validate(raw, strict=True)
        except (ValidationError, TypeError, ValueError):
            raise ToolExecutionError(ErrorCode.INVALID_TOOL_ARGUMENTS) from None
        request = typed_input.model_dump(mode="json")
        if observer:
            observer.validated(request)
        decision = self.check_permission(name)
        if observer:
            observer.permission(decision, tool.risk)
        if not decision.allowed or decision.requires_approval:
            if decision.requires_approval:
                raise ApprovalRequired(decision)
            raise ToolExecutionError(ErrorCode.PERMISSION_DENIED)
        end = min(
            deadline if deadline is not None else math.inf, time.monotonic() + tool.timeout_seconds
        )
        if time.monotonic() >= end:
            raise ToolExecutionError(ErrorCode.TIMEOUT)
        try:
            if observer:
                observer.started()
            process, connection = start_worker(_tool_worker, tool, request)
            try:
                if not connection.poll(max(0, end - time.monotonic())):
                    raise ToolExecutionError(ErrorCode.TIMEOUT)
                response = receive_json(connection)
                if "error" in response:
                    raise ToolExecutionError(ErrorCode(response["error"]))
                return cast(BaseModel, tool.output_model.model_validate(response["output"]))
            finally:
                stop_worker(process, connection)
        except ToolExecutionError:
            raise
        except Exception:  # noqa: BLE001 -- dispatch boundary must return safe typed failures
            raise ToolExecutionError(ErrorCode.TOOL_ERROR) from None
