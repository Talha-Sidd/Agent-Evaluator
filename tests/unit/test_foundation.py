import json
from pathlib import Path

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import RunStatus, Scenario
from agent_reliability_lab.platform.runner.runner import ScenarioRunner


def test_runner_normalizes_trace_and_result() -> None:
    scenario = Scenario(
        scenario_id="test-1",
        task="find timeout",
        repository_files={"client.py": "timeout handling"},
        expected_behavior="find client",
    )

    result = ScenarioRunner().run(RepoPilotDemo(), scenario)

    assert result.status is RunStatus.SUCCEEDED
    assert result.tool_calls[0].name == "repo_search"
    assert [event.event_type for event in result.trace] == [
        "run.started",
        "agent.started",
        "tool.completed",
        "agent.completed",
    ]


def test_smoke_dataset_is_valid_jsonl() -> None:
    path = Path("evals/datasets/repopilot_smoke.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 2
    assert all("scenario_id" in row and "expected_behavior" in row for row in rows)
