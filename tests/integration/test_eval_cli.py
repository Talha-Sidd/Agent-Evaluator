import json
from pathlib import Path

from agent_reliability_lab.cli import main
from agent_reliability_lab.platform.evals.suite import EvaluationSuite

DATASET = Path("evals/datasets/repopilot_smoke.jsonl")


def test_evaluation_suite_runs_all_golden_cases() -> None:
    suite = EvaluationSuite()

    scenarios = suite.load_jsonl(DATASET)
    scorecard = suite.run(scenarios, "repopilot_smoke")

    assert scorecard.total_cases == 10
    assert scorecard.passed_cases == 10
    assert scorecard.failed_cases == []
    assert scorecard.failure_category_counts == {}
    assert scorecard.task_success_rate == 1.0


def test_eval_cli_returns_success_for_passing_suite(capsys: object) -> None:
    exit_code = main(["eval", "--dataset", str(DATASET), "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    output = json.loads(captured.out)
    assert output["total_cases"] == 10
    assert output["task_success_rate"] == 1.0
    assert output["quality_gate"]["passed"] is True


def test_replay_cli_creates_and_runs_case(tmp_path: Path, capsys: object) -> None:
    case_path = tmp_path / "replay-case.json"

    create_exit_code = main(
        [
            "replay",
            "create",
            "--dataset",
            str(DATASET),
            "--scenario-id",
            "repopilot-search-001",
            "--output",
            str(case_path),
        ]
    )
    assert create_exit_code == 0
    assert case_path.exists()
    capsys.readouterr()

    run_exit_code = main(["replay", "run", "--case", str(case_path), "--json"])

    assert run_exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["case_id"] == "repopilot-search-001"
    assert output["passed"] is True
