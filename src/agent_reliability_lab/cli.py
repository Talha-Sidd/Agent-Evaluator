"""Command-line entry points for deterministic evaluation."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from agent_reliability_lab.domain.models import Scenario
from agent_reliability_lab.platform.evals.quality_gate import (
    QualityGate,
    QualityGateConfig,
    QualityGateResult,
)
from agent_reliability_lab.platform.evals.suite import EvaluationSuite, SuiteScorecard
from agent_reliability_lab.platform.replay import ReplayRunner


def _load_gate_config(path: Path) -> QualityGateConfig:
    return QualityGateConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _run_eval(dataset: Path, gate_config_path: Path, as_json: bool) -> int:
    suite = EvaluationSuite()
    scorecard = suite.run(suite.load_jsonl(dataset), dataset.stem)
    gate = QualityGate(_load_gate_config(gate_config_path)).evaluate(scorecard)
    if as_json:
        output = scorecard.model_dump(mode="json")
        output["quality_gate"] = gate.model_dump(mode="json")
        print(json.dumps(output, indent=2))
    else:
        _print_scorecard(scorecard, gate)
    return 0 if gate.passed else 1


def _print_scorecard(scorecard: SuiteScorecard, gate: QualityGateResult) -> None:
    print(f"Suite: {scorecard.suite_name}")
    print(f"Cases: {scorecard.passed_cases}/{scorecard.total_cases} passed")
    print(f"Task success rate: {scorecard.task_success_rate:.1%}")
    if scorecard.failed_cases:
        print("Failed cases: " + ", ".join(scorecard.failed_cases))
    if scorecard.failure_category_counts:
        print("Failure categories: " + json.dumps(scorecard.failure_category_counts, sort_keys=True))
    print(f"Quality gate: {'PASSED' if gate.passed else 'FAILED'}")
    for violation in gate.violations:
        print(f"Gate violation: {violation}")


def _scenario_from_dataset(dataset: Path, scenario_id: str) -> Scenario:
    suite = EvaluationSuite()
    for scenario in suite.load_jsonl(dataset):
        if scenario.scenario_id == scenario_id:
            return scenario
    raise ValueError(f"scenario not found: {scenario_id}")


def _run_replay_create(dataset: Path, scenario_id: str, output: Path) -> int:
    scenario = _scenario_from_dataset(dataset, scenario_id)
    runner = ReplayRunner()
    case = runner.create_case(scenario, scenario_id)
    runner.save_case(case, output)
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
    replay_parser = subparsers.add_parser("replay", help="create or run replay artifacts")
    replay_subparsers = replay_parser.add_subparsers(dest="replay_command", required=True)
    create_parser = replay_subparsers.add_parser("create", help="freeze a scenario baseline")
    create_parser.add_argument("--dataset", type=Path, required=True)
    create_parser.add_argument("--scenario-id", required=True)
    create_parser.add_argument("--output", type=Path, required=True)
    run_parser = replay_subparsers.add_parser("run", help="replay a frozen case")
    run_parser.add_argument("--case", type=Path, required=True)
    run_parser.add_argument("--json", action="store_true", help="print replay result as JSON")
    args = parser.parse_args(argv)

    if args.command == "eval":
        return _run_eval(args.dataset, args.gate_config, args.json)
    if args.command == "replay" and args.replay_command == "create":
        return _run_replay_create(args.dataset, args.scenario_id, args.output)
    if args.command == "replay" and args.replay_command == "run":
        return _run_replay_case(args.case, args.json)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
