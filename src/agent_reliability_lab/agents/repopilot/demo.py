"""A deterministic repository investigation adapter for contract testing."""

from uuid import UUID

from agent_reliability_lab.domain.models import AgentResult, RunStatus, Scenario, ToolCall, TraceEvent
from agent_reliability_lab.domain.protocols import TraceSink


class RepoPilotDemo:
    name = "repopilot-demo"

    def run(self, scenario: Scenario, run_id: UUID, trace: TraceSink) -> AgentResult:
        calls: list[ToolCall] = []
        trace.emit(TraceEvent(run_id=run_id, event_type="agent.started"))

        matching_files = [
            path for path, content in scenario.repository_files.items()
            if any(term.lower() in content.lower() for term in scenario.task.split())
        ]
        calls.append(ToolCall(name="repo_search", arguments={"task": scenario.task}, success=True))
        trace.emit(TraceEvent(
            run_id=run_id,
            event_type="tool.completed",
            tool_name="repo_search",
            success=True,
            detail=f"matched_files={matching_files}",
        ))

        answer = (
            f"RepoPilot found {len(matching_files)} relevant file(s): "
            + (", ".join(matching_files) if matching_files else "none")
        )
        trace.emit(TraceEvent(run_id=run_id, event_type="agent.completed", success=True))
        return AgentResult(
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            status=RunStatus.SUCCEEDED,
            final_answer=answer,
            tool_calls=calls,
        )

