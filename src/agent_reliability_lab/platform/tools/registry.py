"""Typed registry for internal tools; no arbitrary shell execution is exposed."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from agent_reliability_lab.domain.models import PermissionDecision, RiskLevel, ToolAction
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy

InputModel = TypeVar("InputModel", bound=BaseModel)
OutputModel = TypeVar("OutputModel", bound=BaseModel)


class ToolExecutionError(RuntimeError):
    """Raised when a tool cannot be executed safely or successfully."""


class ApprovalRequired(ToolExecutionError):
    """Raised when policy requires human approval before tool execution."""

    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class ToolDefinition[InputModel: BaseModel, OutputModel: BaseModel]:
    name: str
    risk: RiskLevel
    input_model: type[InputModel]
    output_model: type[OutputModel]
    handler: Callable[[InputModel], OutputModel]
    timeout_seconds: float = 5.0


class TypedToolRegistry:
    def __init__(self, permission_policy: DeterministicPermissionPolicy) -> None:
        self._permission_policy = permission_policy
        self._tools: dict[str, ToolDefinition[Any, Any]] = {}

    def register(
        self, tool: ToolDefinition[InputModel, OutputModel]
    ) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition[Any, Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolExecutionError(f"unknown tool: {name}") from exc

    def check_permission(self, name: str) -> PermissionDecision:
        tool = self.get(name)
        return self._permission_policy.check(ToolAction(tool_name=tool.name, risk=tool.risk))

    def execute(self, name: str, arguments: object) -> BaseModel:
        tool = self.get(name)
        decision = self.check_permission(name)
        if not decision.allowed:
            if decision.requires_approval:
                raise ApprovalRequired(decision)
            raise ToolExecutionError(decision.reason)
        try:
            typed_input = tool.input_model.model_validate(arguments)
            output = tool.handler(typed_input)
            return cast(BaseModel, tool.output_model.model_validate(output))
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"tool {name} failed: {exc}") from exc
