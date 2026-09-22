"""Command-line entry points for deterministic evaluation."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from agent_reliability_lab.platform.evals.suite import EvaluationSuite, SuiteScorecard


def _run_eval(dataset: Path, as_json: bool) -> int:
    suite = EvaluationSuite()
    scorecard = suite.run(suite.load_jsonl(dataset), dataset.stem)
    if as_json:
        print(scorecard.model_dump_json(indent=2))
    else:
        _print_scorecard(scorecard)
    return 0 if scorecard.task_success_rate == 1.0 else 1


def _print_scorecard(scorecard: SuiteScorecard) -> None:
    print(f"Suite: {scorecard.suite_name}")
    print(f"Cases: {scorecard.passed_cases}/{scorecard.total_cases} passed")
    print(f"Task success rate: {scorecard.task_success_rate:.1%}")
    if scorecard.failed_cases:
        print("Failed cases: " + ", ".join(scorecard.failed_cases))
    if scorecard.failure_category_counts:
        print("Failure categories: " + json.dumps(scorecard.failure_category_counts, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    eval_parser = subparsers.add_parser("eval", help="run a deterministic evaluation suite")
    eval_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/repopilot_smoke.jsonl"),
    )
    eval_parser.add_argument("--json", action="store_true", help="print the scorecard as JSON")
    args = parser.parse_args(argv)

    if args.command == "eval":
        return _run_eval(args.dataset, args.json)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
