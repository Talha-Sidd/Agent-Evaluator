"""Tools owned by the example application, registered with the harness."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_reliability_lab.domain.models import RiskLevel
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.tools.registry import ToolDefinition, TypedToolRegistry


class CalculateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: int
    operation: Literal["add", "subtract", "multiply"]
    right: int


class CalculateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class ProtectedActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str


class ProtectedActionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: bool


def calculate(input_data: CalculateInput) -> CalculateOutput:
    if input_data.operation == "add":
        value = input_data.left + input_data.right
    elif input_data.operation == "subtract":
        value = input_data.left - input_data.right
    else:
        value = input_data.left * input_data.right
    return CalculateOutput(value=value)


def protected_action(input_data: ProtectedActionInput) -> ProtectedActionOutput:
    """Harmless handler used only to verify that approval-required work is blocked."""
    return ProtectedActionOutput(completed=True)


def build_registry(
    *,
    include_protected_action: bool = False,
    calculator_handler: Callable[[CalculateInput], CalculateOutput] = calculate,
) -> TypedToolRegistry:
    registry = TypedToolRegistry(DeterministicPermissionPolicy())
    registry.register(
        ToolDefinition(
            name="calculate",
            risk=RiskLevel.LOW,
            input_model=CalculateInput,
            output_model=CalculateOutput,
            handler=calculator_handler,
        )
    )
    if include_protected_action:
        registry.register(
            ToolDefinition(
                name="protected_action",
                risk=RiskLevel.HIGH,
                input_model=ProtectedActionInput,
                output_model=ProtectedActionOutput,
                handler=protected_action,
            )
        )
    return registry
