"""Evaluate safe refund behavior and prove injection checks reject an unsafe agent."""

from pathlib import Path

from examples.refund_support.agent import RefundSupportAgent, UnsafeRefundSupportAgent
from examples.refund_support.tools import build_refund_registry

from agent_reliability_lab.domain.models import ErrorCode, Scenario
from agent_reliability_lab.domain.protocols import AgentAdapter
from agent_reliability_lab.platform.evals.quality_gate import QualityGate, QualityGateConfig
from agent_reliability_lab.platform.evals.suite import EvaluationSuite
from agent_reliability_lab.platform.runner.runner import ScenarioRunner

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "examples/refund_support/scenarios.jsonl"
GATE_CONFIG = QualityGateConfig.model_validate_json(
    (ROOT / "evals/quality_gate.json").read_text(encoding="utf-8")
)


def load_scenarios() -> list[Scenario]:
    return EvaluationSuite().load_jsonl(SCENARIOS)


def make_suite(agent: AgentAdapter) -> EvaluationSuite:
    return EvaluationSuite(
        agent=agent,
        runner=ScenarioRunner(registry=build_refund_registry()),
    )


def test_safe_refund_agent_passes_direct_and_indirect_injection_scenarios() -> None:
    scorecard = make_suite(RefundSupportAgent()).run(load_scenarios(), "refund-support")

    assert scorecard.passed_cases == 4
    assert scorecard.total_cases == 4
    assert scorecard.failure_category_counts == {}
    gate = QualityGate(GATE_CONFIG).evaluate(scorecard)
    assert gate.passed is True
    assert gate.security_violation_rate == 0.0

    for case in scorecard.cases:
        assert case.evaluation.passed is True
        assert all(call.name != "issue_refund" for call in case.result.tool_calls)


def test_injection_following_control_fails_agent_and_security_gates() -> None:
    attack_cases = [scenario for scenario in load_scenarios() if scenario.category == "security"]
    scorecard = make_suite(UnsafeRefundSupportAgent()).run(attack_cases, "unsafe-refund-control")

    assert scorecard.passed_cases == 0
    assert scorecard.failure_category_counts["security_violation"] == 2
    gate = QualityGate(GATE_CONFIG).evaluate(scorecard)
    assert gate.passed is False
    assert gate.security_violation_rate == 1.0
    assert any("security violation rate" in violation for violation in gate.violations)

    for case in scorecard.cases:
        checks = {item.name: item for item in case.evaluation.checks}
        assert checks["prohibited_tool_requests"].passed is False
        assert checks["forbidden_output_terms"].passed is False
        assert checks["forbidden_tools"].passed is True
        attempted_refund = next(
            call for call in case.result.tool_calls if call.name == "issue_refund"
        )
        assert attempted_refund.error_code is ErrorCode.APPROVAL_REQUIRED
        assert attempted_refund.executed is False
