import json
from pathlib import Path
from uuid import UUID

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.cli import main
from agent_reliability_lab.domain.models import AgentResult, AgentTask, Scenario
from agent_reliability_lab.domain.protocols import ToolExecutor
from agent_reliability_lab.platform.evals.comparison import (
    create_snapshot,
    load_snapshot,
    save_snapshot,
)
from agent_reliability_lab.platform.evals.suite import EvaluationSuite


class WrongQueryAgent:
    name = "wrong-query"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        return RepoPilotDemo().run(task.model_copy(update={"task": "absent"}), run_id, tools)


def test_cli_snapshot_and_comparison_lifecycle(tmp_path: Path, capsys) -> None:
    scenario = Scenario(
        scenario_id="comparison-case", task="needle",
        repository_files={"sample.txt": "needle private-fixture-canary"},
        expected_behavior="find sample", expected_matching_files=["sample.txt"],
        expected_tools=["repo_search"],
    )
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(scenario.model_dump_json() + "\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    assert main([
        "eval", "--dataset", str(dataset), "--snapshot", str(baseline),
        "--agent-version", "v1", "--json",
    ]) == 0
    capsys.readouterr()
    assert "private-fixture-canary" not in baseline.read_text(encoding="utf-8")
    assert "final_answer" not in baseline.read_text(encoding="utf-8")
    assert main(["compare", "--baseline", str(baseline), "--candidate", str(baseline),
                 "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["unchanged_cases"] == ["comparison-case"]

    # A real candidate tool argument change is executed through the same harness.
    scorecard = EvaluationSuite(agent=WrongQueryAgent()).run([scenario], "candidate")
    assert scorecard.passed_cases == 0
    candidate = tmp_path / "candidate.json"
    save_snapshot(create_snapshot([scenario], scorecard, "v2"), candidate)
    assert main(["compare", "--baseline", str(baseline), "--candidate", str(candidate),
                 "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["regressions"] == ["comparison-case"]
    assert load_snapshot(baseline).cases[0].passed


def test_compare_cli_sanitizes_invalid_artifact_errors(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"api_key":"private-canary"}', encoding="utf-8")
    assert main(["compare", "--baseline", str(path), "--candidate", str(path)]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"error": "invalid_input"}
    assert "private-canary" not in captured.err


def test_snapshot_requires_explicit_version_before_running(tmp_path: Path, capsys) -> None:
    assert main(["eval", "--snapshot", str(tmp_path / "out.json")]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "invalid_input"}


def test_deeply_nested_artifact_is_sanitized_invalid_input(tmp_path: Path, capsys) -> None:
    path = tmp_path / "nested.json"
    path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    assert main(["compare", "--baseline", str(path), "--candidate", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "invalid_input"}
