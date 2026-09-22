"""Command-line entry points for deterministic evaluation."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from agent_reliability_lab.platform.evals.quality_gate import (
    QualityGate,
    QualityGateConfig,
    QualityGateResult,
)
from agent_reliability_lab.platform.evals.suite import EvaluationSuite, SuiteScorecard


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
    args = parser.parse_args(argv)

    if args.command == "eval":
        return _run_eval(args.dataset, args.gate_config, args.json)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
