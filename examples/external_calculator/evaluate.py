"""Run the external example agent against scenarios and compare its baseline."""

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
from examples.external_calculator.agent import ExternalCalculatorAgent, UnsafeCalculatorAgent
from examples.external_calculator.tools import build_registry

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-version", default="external-calculator-v1")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline-starter-v3.json")
    parser.add_argument("--snapshot", type=Path, help="write candidate snapshot without overwriting")
    parser.add_argument(
        "--initialize-baseline",
        action="store_true",
        help="create the initial baseline once, then exit",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()

    suite = EvaluationSuite(
        agent=ExternalCalculatorAgent(),
        runner=ScenarioRunner(registry=build_registry(include_protected_action=True)),
    )
    scenarios = suite.load_jsonl(HERE / "scenarios.jsonl")
    scorecard = suite.run(scenarios, "external-calculator")
    security_scenario = next(
        scenario for scenario in scenarios
        if scenario.scenario_id == "calculator-injection-protected-action"
    )
    unsafe_suite = EvaluationSuite(
        agent=UnsafeCalculatorAgent(),
        runner=ScenarioRunner(registry=build_registry(include_protected_action=True)),
    )
    unsafe_scenario = security_scenario.model_copy(update={"max_steps": 2})
    unsafe_scorecard = unsafe_suite.run([unsafe_scenario], "external-calculator-unsafe-control")
    unsafe_report = unsafe_scorecard.cases[0]
    unsafe_control_rejected = (
        unsafe_scorecard.passed_cases == 0
        and any(
            not check.passed and check.name == "prohibited_tool_requests"
            for check in unsafe_report.evaluation.checks
        )
        and len(unsafe_report.result.tool_calls) == 2
        and unsafe_report.result.tool_calls[1].permission_allowed is False
        and unsafe_report.result.tool_calls[1].executed is False
        and any(
            event.event_type == "permission.checked"
            and event.tool_name == "protected_action"
            and event.success is False
            for event in unsafe_report.result.trace
        )
    )
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
            "agent": ExternalCalculatorAgent.name,
            "scorecard": scorecard.model_dump(mode="json"),
            "baseline_comparison": comparison.model_dump(mode="json"),
            "unsafe_control": {
                "agent": UnsafeCalculatorAgent.name,
                "evaluation_passed": unsafe_report.evaluation.passed,
                "harness_rejected_control": unsafe_control_rejected,
                "tool_calls": [call.model_dump(mode="json") for call in unsafe_report.result.tool_calls],
                "trace": [event.model_dump(mode="json") for event in unsafe_report.result.trace],
            },
        }, indent=2))
    else:
        print(f"Agent: {ExternalCalculatorAgent.name} ({args.agent_version})")
        print(f"Scenarios passed: {scorecard.passed_cases}/{scorecard.total_cases} "
              f"({scorecard.task_success_rate:.0%})")
        if scorecard.latency is not None:
            p50 = scorecard.latency.run.p50_ms
            p95 = scorecard.latency.run.p95_ms
            if p50 is not None and p95 is not None:
                print(f"Run latency p50/p95: {p50:.1f}/{p95:.1f} ms")
        print("Tool calls: " + str(sum(len(case.result.tool_calls) for case in scorecard.cases)))
        print("Failures: " + str(scorecard.failure_category_counts or "none"))
        print(f"Baseline: {comparison.baseline_version} "
              f"({comparison.baseline_success_rate:.0%})")
        print(f"Comparison: {'PASSED' if comparison.passed else 'FAILED'}")
        print(f"Unsafe control rejected and blocked: {'YES' if unsafe_control_rejected else 'NO'}")
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
    return 0 if comparison.passed and unsafe_control_rejected else 1


if __name__ == "__main__":
    raise SystemExit(main())
