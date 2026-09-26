"""Exercise the consumer-facing top-level evaluation helper."""

from pathlib import Path

from examples.external_calculator.agent import ExternalCalculatorAgent
from examples.external_calculator.tools import build_registry

from agent_reliability_lab import evaluate

ROOT = Path(__file__).resolve().parents[2]


def test_public_evaluate_returns_summary_and_case_evidence() -> None:
    report = evaluate(
        agent=ExternalCalculatorAgent(),
        scenarios=ROOT / "examples/external_calculator/scenarios.jsonl",
        tools=build_registry(include_protected_action=True),
    )

    summary = report.summary()
    assert report.passed is True
    assert report.passed_cases == report.total_cases == 4
    assert summary["suite"] == "external-calculator"
    assert summary["task_success_rate"] == 1.0
    assert summary["tool_calls"] == 4
    assert len(report.cases) == 4
    security_case = next(
        case for case in report.cases
        if case.evaluation.scenario_id == "calculator-injection-protected-action"
    )
    assert security_case.evaluation.passed is True
