"""Command-line entry points for deterministic evaluation."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_reliability_lab.domain.models import Scenario
from agent_reliability_lab.platform.evals.comparison import (
    compare_snapshots,
    create_snapshot,
    load_snapshot,
    save_snapshot,
)
from agent_reliability_lab.platform.evals.quality_gate import (
    QualityGate,
    QualityGateConfig,
    QualityGateResult,
)
from agent_reliability_lab.platform.evals.suite import EvaluationSuite, SuiteScorecard
from agent_reliability_lab.platform.replay import ReplayRunner
from agent_reliability_lab.platform.storage.postgres import PostgresRunRepository, StorageError


def _load_gate_config(path: Path) -> QualityGateConfig:
    return QualityGateConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _run_eval(
    dataset: Path, gate_config_path: Path, as_json: bool,
    snapshot_path: Path | None = None, agent_version: str | None = None,
) -> int:
    if (snapshot_path is None) != (agent_version is None):
        raise ValueError("snapshot and agent version must be supplied together")
    config = _load_gate_config(gate_config_path)
    suite = EvaluationSuite()
    scenarios = suite.load_jsonl(dataset)
    scorecard = suite.run(scenarios, dataset.stem)
    gate = QualityGate(config).evaluate(scorecard)
    if snapshot_path is not None and agent_version is not None:
        save_snapshot(create_snapshot(scenarios, scorecard, agent_version), snapshot_path)
    if as_json:
        output = scorecard.model_dump(mode="json")
        output["quality_gate"] = gate.model_dump(mode="json")
        print(json.dumps(output, indent=2))
    else:
        _print_scorecard(scorecard, gate)
    return 0 if gate.passed else 1


def _run_compare(baseline: Path, candidate: Path, gate_config: Path, as_json: bool) -> int:
    result = compare_snapshots(
        load_snapshot(baseline), load_snapshot(candidate), _load_gate_config(gate_config)
    )
    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"Comparison: {result.baseline_version} -> {result.candidate_version}")
        print(f"Task success: {result.baseline_success_rate:.1%} -> "
              f"{result.candidate_success_rate:.1%}")
        print("Regressions: " + (", ".join(result.regressions) or "none"))
        print("Improvements: " + (", ".join(result.improvements) or "none"))
        print(f"Comparison gate: {'PASSED' if result.passed else 'FAILED'}")
        for violation in result.violations:
            print(f"Gate violation: {violation}")
    return 0 if result.passed else 1


def _print_scorecard(scorecard: SuiteScorecard, gate: QualityGateResult) -> None:
    print(f"Suite: {scorecard.suite_name}")
    print(f"Cases: {scorecard.passed_cases}/{scorecard.total_cases} passed")
    print(f"Task success rate: {scorecard.task_success_rate:.1%}")
    if scorecard.failed_cases:
        print("Failed cases: " + ", ".join(scorecard.failed_cases))
    if scorecard.failure_category_counts:
        print(
            "Failure categories: " + json.dumps(scorecard.failure_category_counts, sort_keys=True)
        )
    print(f"Quality gate: {'PASSED' if gate.passed else 'FAILED'}")
    for violation in gate.violations:
        print(f"Gate violation: {violation}")


def _scenario_from_dataset(dataset: Path, scenario_id: str) -> Scenario:
    suite = EvaluationSuite()
    for scenario in suite.load_jsonl(dataset):
        if scenario.scenario_id == scenario_id:
            return scenario
    raise ValueError(f"scenario not found: {scenario_id}")


def _run_replay_create(dataset: Path, scenario_id: str, output: Path, force: bool = False) -> int:
    scenario = _scenario_from_dataset(dataset, scenario_id)
    runner = ReplayRunner()
    case = runner.create_case(scenario, scenario_id)
    runner.save_case(case, output, overwrite=force)
    print(f"Replay case created: {output}")
    return 0


def _run_replay_case(case_path: Path, as_json: bool) -> int:
    runner = ReplayRunner()
    result = runner.replay(runner.load_case(case_path))
    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"Replay case: {result.case_id}")
        print(f"Replay: {'PASSED' if result.passed else 'FAILED'}")
        for difference in result.differences:
            print(f"Difference: {difference}")
    return 0 if result.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    eval_parser = subparsers.add_parser("eval", help="run a deterministic evaluation suite")
    eval_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/repopilot_smoke.jsonl"),
    )
    eval_parser.add_argument(
        "--gate-config",
        type=Path,
        default=Path("evals/quality_gate.json"),
    )
    eval_parser.add_argument("--json", action="store_true", help="print the scorecard as JSON")
    eval_parser.add_argument("--snapshot", type=Path, help="write a new evaluation snapshot")
    eval_parser.add_argument("--agent-version", help="version label for the evaluated checkout")
    compare_parser = subparsers.add_parser("compare", help="compare two evaluation snapshots")
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--gate-config", type=Path, default=Path("evals/quality_gate.json"))
    compare_parser.add_argument("--json", action="store_true")
    replay_parser = subparsers.add_parser("replay", help="create or run replay artifacts")
    replay_subparsers = replay_parser.add_subparsers(dest="replay_command", required=True)
    create_parser = replay_subparsers.add_parser("create", help="freeze a scenario baseline")
    create_parser.add_argument("--dataset", type=Path, required=True)
    create_parser.add_argument("--scenario-id", required=True)
    create_parser.add_argument("--output", type=Path, required=True)
    create_parser.add_argument("--force", action="store_true", help="replace an existing artifact")
    run_parser = replay_subparsers.add_parser("run", help="replay a frozen case")
    run_parser.add_argument("--case", type=Path, required=True)
    run_parser.add_argument("--json", action="store_true", help="print replay result as JSON")
    db_parser = subparsers.add_parser("db", help="manage durable evidence schema")
    db_parser.add_argument("operation", choices=["migrate"])
    args = parser.parse_args(argv)

    try:
        if args.command == "eval":
            return _run_eval(
                args.dataset, args.gate_config, args.json, args.snapshot, args.agent_version
            )
        if args.command == "compare":
            return _run_compare(args.baseline, args.candidate, args.gate_config, args.json)
        if args.command == "replay" and args.replay_command == "create":
            return _run_replay_create(args.dataset, args.scenario_id, args.output, args.force)
        if args.command == "replay" and args.replay_command == "run":
            return _run_replay_case(args.case, args.json)
        if args.command == "db" and args.operation == "migrate":
            dsn = os.environ.get("ARL_DATABASE_URL")
            if not dsn:
                raise ValueError("ARL_DATABASE_URL is required")
            PostgresRunRepository(dsn).migrate()
            print("Database migrations applied.")
            return 0
    except StorageError:
        print(json.dumps({"error": "storage_error"}), file=sys.stderr)
        return 2
    except (OSError, ValueError, ValidationError) as exc:
        # Never print validation payloads, file contents, or arbitrary exception strings.
        code = "artifact_exists" if isinstance(exc, FileExistsError) else "invalid_input"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
