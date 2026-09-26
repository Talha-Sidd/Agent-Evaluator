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
    assert scorecard.latency is not None
    assert scorecard.latency.run.samples == 10
    assert scorecard.latency.run.missing == 0
    assert scorecard.latency.agent_worker_startup.missing == 0
    assert scorecard.latency.tool_request.missing == 0
    assert scorecard.latency.tool_worker_startup.missing == 0


def test_eval_cli_returns_success_for_passing_suite(capsys: object) -> None:
    exit_code = main(["eval", "--dataset", str(DATASET), "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    output = json.loads(captured.out)
    assert output["total_cases"] == 10
    assert output["task_success_rate"] == 1.0
    assert output["quality_gate"]["passed"] is True
    assert all(output["safety_checks"].values())
    assert len(output["cases"]) == 10
    assert output["latency"]["run"]["samples"] == 10


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


def test_committed_replay_artifact_matches_current_evaluator(capsys: object) -> None:
    case_path = Path("evals/replays/search-001.json")

    exit_code = main(["replay", "run", "--case", str(case_path), "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["case_id"] == "repopilot-search-001"
    assert output["passed"] is True
    assert output["differences"] == []


def test_cli_reports_invalid_input_without_traceback_or_payload(tmp_path, capsys) -> None:
    dataset = tmp_path / "bad.jsonl"
    dataset.write_text('{"task":"API_KEY=private-canary"}', encoding="utf-8")
    assert main(["eval", "--dataset", str(dataset), "--json"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"error": "invalid_input"}
    assert "private-canary" not in captured.err
