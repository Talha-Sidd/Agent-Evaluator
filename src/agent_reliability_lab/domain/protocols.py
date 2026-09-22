"""Structural interfaces used by the platform."""

from typing import Any, Protocol
from uuid import UUID

from agent_reliability_lab.domain.models import AgentResult, AgentTask, TraceEvent


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None:
        """Record one normalized event."""


class AgentAdapter(Protocol):
    name: str

    def run(self, task: AgentTask, run_id: UUID, tools: "ToolExecutor") -> AgentResult:
        """Execute using only the task inputs and harness-mediated tools."""


class ToolExecutor(Protocol):
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Request a validated and authorized action from the harness."""
