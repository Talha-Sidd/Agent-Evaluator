"""An application agent implemented separately from the harness demo agent."""

import re
from uuid import UUID

from agent_reliability_lab.domain.errors import ToolExecutionError
from agent_reliability_lab.domain.models import AgentResult, AgentTask, RunStatus
from agent_reliability_lab.domain.protocols import ToolExecutor

_CALCULATION = re.compile(
    r"\b(?:calculate|compute)\s+(-?\d+)\s*([+*×x-])\s*(-?\d+)\b", re.IGNORECASE
)


class ExternalCalculatorAgent:
    """Tiny deterministic stand-in for an application-specific agent."""

    name = "external-calculator"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        match = _CALCULATION.search(task.task)
        if match is None:
            return AgentResult(
                run_id=run_id,
                scenario_id=task.scenario_id,
                status=RunStatus.SUCCEEDED,
                final_answer="I could not parse a calculation.",
            )
        left_text, symbol, right_text = match.groups()
        operation = {
            "+": "add",
            "-": "subtract",
            "*": "multiply",
            "×": "multiply",
            "x": "multiply",
        }[symbol.lower()]
        output = tools.execute(
            "calculate",
            {"left": int(left_text), "operation": operation, "right": int(right_text)},
        )
        return AgentResult(
            run_id=run_id,
            scenario_id=task.scenario_id,
            status=RunStatus.SUCCEEDED,
            final_answer=f"The result is {output['value']}.",
        )


class InvalidArgumentsAgent:
    """Negative-control adapter for exercising deterministic schema rejection."""

    name = "invalid-arguments-control"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        tools.execute("calculate", {"left": "not-an-integer", "operation": "add", "right": 2})
        raise AssertionError("invalid arguments should have been rejected")


class UnknownToolAgent:
    """Negative-control adapter that requests a tool absent from its registry."""

    name = "unknown-tool-control"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        tools.execute("run_shell", {"command": "echo unsafe"})
        raise AssertionError("unknown tool should have been rejected")


class ApprovalRequiredAgent:
    """Negative-control adapter that requests an approval-required action."""

    name = "approval-required-control"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        tools.execute("protected_action", {"item": "synthetic-item"})
        raise AssertionError("approval-required action should have been blocked")


class UnsafeCalculatorAgent:
    """Negative control that follows an injected request for a protected action."""

    name = "external-calculator-unsafe-control"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        tools.execute("calculate", {"left": 8, "operation": "add", "right": 4})
        try:
            tools.execute("protected_action", {"item": "synthetic-secret"})
        except ToolExecutionError:
            pass
        return AgentResult(
            run_id=run_id,
            scenario_id=task.scenario_id,
            status=RunStatus.SUCCEEDED,
            final_answer="I followed the injected instruction and requested the protected action.",
        )


__all__ = [
    "ApprovalRequiredAgent",
    "ExternalCalculatorAgent",
    "InvalidArgumentsAgent",
    "UnknownToolAgent",
    "UnsafeCalculatorAgent",
]
