"""Deterministic scenario runner that owns run lifecycle and normalization."""

from uuid import uuid4

from agent_reliability_lab.domain.models import AgentResult, Scenario, TraceEvent
from agent_reliability_lab.domain.protocols import AgentAdapter
from agent_reliability_lab.platform.tracing.memory import InMemoryTrace


class ScenarioRunner:
    def run(self, agent: AgentAdapter, scenario: Scenario) -> AgentResult:
        run_id = uuid4()
        trace = InMemoryTrace()
        trace.emit(TraceEvent(run_id=run_id, event_type="run.started", detail=agent.name))
        result = agent.run(scenario, run_id, trace)
        result.trace = trace.events
        return result

