"""Structural interfaces used by the platform."""

from typing import Protocol
from uuid import UUID

from agent_reliability_lab.domain.models import AgentResult, Scenario, TraceEvent


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None:
        """Record one normalized event."""


class AgentAdapter(Protocol):
    name: str

    def run(self, scenario: Scenario, run_id: UUID, trace: TraceSink) -> AgentResult:
        """Execute a scenario using the platform-provided run identity and trace sink."""

