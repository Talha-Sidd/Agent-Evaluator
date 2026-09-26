"""Evaluate the synthetic refund-support agent and compare a reviewed baseline."""

import argparse
import json
from pathlib import Path

from agent_reliability_lab.platform.evals.comparison import (
    compare_snapshots,
    create_snapshot,
    load_snapshot,
    save_snapshot,
)
from agent_reliability_lab.platform.evals.quality_gate import QualityGateConfig
from agent_reliability_lab.platform.evals.suite import EvaluationSuite
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from examples.refund_support.agent import RefundSupportAgent
from examples.refund_support.tools import build_refund_registry

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-version", default=RefundSupportAgent.name)
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline-starter-v2.json")
    parser.add_argument("--snapshot", type=Path, help="write candidate snapshot without overwriting")
    parser.add_argument(
        "--initialize-baseline",
        action="store_true",
        help="create the initial baseline once, then exit",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()

    suite = EvaluationSuite(
        agent=RefundSupportAgent(),
        runner=ScenarioRunner(registry=build_refund_registry()),
    )
    scenarios = suite.load_jsonl(HERE / "scenarios.jsonl")
    scorecard = suite.run(scenarios, "refund-support-synthetic")
    candidate = create_snapshot(scenarios, scorecard, args.agent_version)
    if args.snapshot:
        snapshot_path = args.snapshot if args.snapshot.is_absolute() else ROOT / args.snapshot
        save_snapshot(candidate, snapshot_path)

    baseline_path = args.baseline if args.baseline.is_absolute() else ROOT / args.baseline
    if args.initialize_baseline:
        save_snapshot(candidate, baseline_path)
        print(f"Initial baseline created: {baseline_path}")
        return 0 if scorecard.passed_cases == scorecard.total_cases else 1
    comparison = compare_snapshots(
        load_snapshot(baseline_path),
        candidate,
        QualityGateConfig.model_validate_json((ROOT / "evals/quality_gate.json").read_text()),
    )
    if args.json:
        print(json.dumps({
            "agent": RefundSupportAgent.name,
            "scorecard": scorecard.model_dump(mode="json"),
            "baseline_comparison": comparison.model_dump(mode="json"),
        }, indent=2))
    else:
        print(f"Agent: {RefundSupportAgent.name} ({args.agent_version})")
        print(f"Scenarios passed: {scorecard.passed_cases}/{scorecard.total_cases} "
              f"({scorecard.task_success_rate:.0%})")
        if scorecard.latency is not None:
            p50 = scorecard.latency.run.p50_ms
            p95 = scorecard.latency.run.p95_ms
            if p50 is not None and p95 is not None:
                print(f"Run latency p50/p95: {p50:.1f}/{p95:.1f} ms")
        print(f"Security violation rate: "
              f"{comparison.candidate_gate.security_violation_rate:.0%}")
        print(f"Baseline: {comparison.baseline_version} "
              f"({comparison.baseline_success_rate:.0%})")
        print(f"Comparison: {'PASSED' if comparison.passed else 'FAILED'}")
        print("Regressions: " + (", ".join(comparison.regressions) or "none"))
        for case in scorecard.cases:
            checks = sum(item.passed for item in case.evaluation.checks)
            total = len(case.evaluation.checks)
            tools = ", ".join(call.name for call in case.result.tool_calls) or "none"
            duration = case.result.timing.run_duration_ms if case.result.timing else 0.0
            print(f"- {case.evaluation.scenario_id}: "
                  f"{'PASS' if case.evaluation.passed else 'FAIL'}; "
                  f"checks {checks}/{total}; tools {tools}; "
                  f"{duration:.1f} ms")
    return 0 if comparison.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
