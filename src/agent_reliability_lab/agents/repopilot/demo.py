"""Deterministic search adapter; permissions and evidence belong to the harness."""

from uuid import UUID

from agent_reliability_lab.domain.models import AgentResult, AgentTask, RunStatus
from agent_reliability_lab.domain.protocols import ToolExecutor
from agent_reliability_lab.platform.tools.repopilot import RepoSearchOutput


class RepoPilotDemo:
    name = "repopilot-demo"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        output = RepoSearchOutput.model_validate(
            tools.execute(
                "repo_search",
                {"query": task.task, "repository_files": task.repository_files},
            )
        )
        matches = output.matching_files
        return AgentResult(
            run_id=run_id,
            scenario_id=task.scenario_id,
            status=RunStatus.SUCCEEDED,
            final_answer=f"RepoPilot found {len(matches)} relevant file(s): "
            + (", ".join(matches) if matches else "none"),
        )
