"""Structural interfaces used by the platform."""

from typing import Any, Protocol
from uuid import UUID

from agent_reliability_lab.domain.model_gateway import ModelRequest, ModelResponse
from agent_reliability_lab.domain.models import AgentResult, AgentTask, StoredRun, TraceEvent


class TraceSink(Protocol):
    """Consumer interface for normalized trace events."""

    def emit(self, event: TraceEvent) -> None:
        """Record one normalized event."""


class AgentAdapter(Protocol):
    """Agent boundary that receives task data and requests tools through the harness."""

    name: str

    def run(self, task: AgentTask, run_id: UUID, tools: "ToolExecutor") -> AgentResult:
        """Execute using only the task inputs and harness-mediated tools."""


class ToolExecutor(Protocol):
    """Restricted tool-request interface exposed to an agent implementation."""

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Request a validated and authorized action from the harness."""


class ModelExecutor(ToolExecutor, Protocol):
    """Restricted model-request interface mediated by the parent harness."""

    def complete(self, request: ModelRequest) -> ModelResponse: ...


class RunRepository(Protocol):
    """Durable evidence boundary; storage errors must be raised to the caller."""

    def save(self, record: StoredRun, *, max_runs: int, max_bytes: int) -> None:
        """Atomically retain a completed run and enforce storage limits."""

    def get(self, run_id: UUID, owner: str) -> StoredRun | None:
        """Return a copy of unexpired evidence visible to this owner."""
