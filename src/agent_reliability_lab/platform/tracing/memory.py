"""Simple trace sink; persistence is intentionally a later milestone."""

from agent_reliability_lab.domain.models import TraceEvent


class InMemoryTrace:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)
