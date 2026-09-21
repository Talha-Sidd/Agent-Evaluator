"""A deterministic repository investigation adapter for contract testing."""

from typing import cast
from uuid import UUID

from agent_reliability_lab.domain.models import (
    AgentResult,
    RunStatus,
    Scenario,
    ToolCall,
    TraceEvent,
)
from agent_reliability_lab.domain.protocols import TraceSink
from agent_reliability_lab.platform.tools.registry import ToolExecutionError
from agent_reliability_lab.platform.tools.repopilot import (
    RepoSearchOutput,
    build_repopilot_registry,
)


class RepoPilotDemo:
    name = "repopilot-demo"

    def run(self, scenario: Scenario, run_id: UUID, trace: TraceSink) -> AgentResult:
        calls: list[ToolCall] = []
        trace.emit(TraceEvent(run_id=run_id, event_type="agent.started"))

        registry = build_repopilot_registry()
        try:
            search_result = registry.execute(
                "repo_search",
                {"query": scenario.task, "repository_files": scenario.repository_files},
            )
            matching_files = cast(RepoSearchOutput, search_result).matching_files
            calls.append(ToolCall(name="repo_search", arguments={"task": scenario.task}, success=True))
            trace.emit(TraceEvent(
                run_id=run_id,
                event_type="tool.completed",
                tool_name="repo_search",
                success=True,
                detail=f"matched_files={matching_files}",
            ))
        except ToolExecutionError as exc:
            calls.append(ToolCall(name="repo_search", arguments={"task": scenario.task}, success=False))
            trace.emit(TraceEvent(
                run_id=run_id,
                event_type="tool.failed",
                tool_name="repo_search",
                success=False,
                detail=str(exc),
            ))
            return AgentResult(
                run_id=run_id,
                scenario_id=scenario.scenario_id,
                status=RunStatus.FAILED,
                final_answer="RepoPilot could not search the repository.",
                tool_calls=calls,
                error=str(exc),
            )

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
