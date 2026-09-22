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
    assert scorecard.task_success_rate == 1.0


def test_eval_cli_returns_success_for_passing_suite(capsys: object) -> None:
    exit_code = main(["eval", "--dataset", str(DATASET), "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    output = json.loads(captured.out)
    assert output["total_cases"] == 10
    assert output["task_success_rate"] == 1.0
