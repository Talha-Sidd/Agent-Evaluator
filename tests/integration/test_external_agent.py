"""Exercise an application-owned agent and its tools through the public harness boundary."""

from pathlib import Path
from uuid import UUID

import pytest
from examples.external_calculator.agent import (
    ApprovalRequiredAgent,
    ExternalCalculatorAgent,
    InvalidArgumentsAgent,
    UnknownToolAgent,
    UnsafeCalculatorAgent,
)
from examples.external_calculator.tools import (
    CalculateInput,
    CalculateOutput,
    build_registry,
)

from agent_reliability_lab.domain.models import AgentResult, AgentTask, ErrorCode, Scenario
from agent_reliability_lab.domain.protocols import ToolExecutor
from agent_reliability_lab.platform.evals.comparison import (
    compare_snapshots,
    create_snapshot,
    load_snapshot,
)
from agent_reliability_lab.platform.evals.quality_gate import QualityGateConfig
from agent_reliability_lab.platform.evals.suite import EvaluationSuite
from agent_reliability_lab.platform.runner.runner import ScenarioRunner

ROOT = Path(__file__).resolve().parents[2]


def test_external_agent_runs_its_own_tools_and_scenarios() -> None:
    suite = EvaluationSuite(
        agent=ExternalCalculatorAgent(),
        runner=ScenarioRunner(registry=build_registry(include_protected_action=True)),
    )
    scenarios = suite.load_jsonl(ROOT / "examples/external_calculator/scenarios.jsonl")

    scorecard = suite.run(scenarios, "external-calculator")

    assert scorecard.passed_cases == 4
    assert scorecard.total_cases == 4
    comparison = compare_snapshots(
        load_snapshot(ROOT / "examples/external_calculator/baseline-starter-v3.json"),
        create_snapshot(scenarios, scorecard, "external-calculator-test"),
        QualityGateConfig.model_validate_json((ROOT / "evals/quality_gate.json").read_text()),
    )
    assert comparison.passed is True
    assert comparison.regressions == []
    for case in scorecard.cases:
        if case.result.scenario_id == "calculator-injection-protected-action":
            assert [call.name for call in case.result.tool_calls] == ["calculate"]
            assert case.evaluation.passed is True
            continue
        assert [call.name for call in case.result.tool_calls] == ["calculate"]
        assert case.result.tool_calls[0].permission_allowed is True
        assert case.result.tool_calls[0].executed is True
        assert case.result.tool_calls[0].success is True
        assert case.evaluation.passed is True


def test_unsafe_external_agent_fails_security_case_and_policy_blocks_handler() -> None:
    suite = EvaluationSuite(
        agent=UnsafeCalculatorAgent(),
        runner=ScenarioRunner(
            registry=build_registry(include_protected_action=True),
        ),
    )
    scenarios = suite.load_jsonl(ROOT / "examples/external_calculator/scenarios.jsonl")
    security_case = next(
        scenario for scenario in scenarios
        if scenario.scenario_id == "calculator-injection-protected-action"
    )
    scenario = security_case.model_copy(update={"max_steps": 2})

    scorecard = suite.run([scenario], "external-calculator-unsafe-control")

    assert scorecard.passed_cases == 0
    report = scorecard.cases[0]
    assert report.evaluation.passed is False
    assert any(
        check.name == "prohibited_tool_requests" and not check.passed
        for check in report.evaluation.checks
    )
    assert [call.name for call in report.result.tool_calls] == [
        "calculate", "protected_action"
    ]
    blocked_call = report.result.tool_calls[1]
    assert blocked_call.permission_allowed is False
    assert blocked_call.requires_approval is True
    assert blocked_call.executed is False
    assert any(
        event.event_type == "permission.checked"
        and event.tool_name == "protected_action"
        and event.success is False
        for event in report.result.trace
    )


class HandlerFailureAgent:
    name = "handler-failure-control"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        tools.execute("calculate", {"left": 7, "operation": "add", "right": 5})
        raise AssertionError("the registered test handler should fail")


def failing_calculator(input_data: CalculateInput) -> CalculateOutput:
    raise RuntimeError("synthetic tool failure")


def control_scenario() -> Scenario:
    return Scenario(
        scenario_id="external-control",
        task="Control case",
        expected_behavior="Exercise one negative tool-boundary case.",
        timeout_seconds=10,
    )


@pytest.mark.parametrize(
    ("agent", "expected_error", "registry_options"),
    [
        (InvalidArgumentsAgent(), ErrorCode.INVALID_TOOL_ARGUMENTS, {}),
        (UnknownToolAgent(), ErrorCode.TOOL_NOT_FOUND, {}),
        (
            ApprovalRequiredAgent(),
            ErrorCode.APPROVAL_REQUIRED,
            {"include_protected_action": True},
        ),
        (
            HandlerFailureAgent(),
            ErrorCode.TOOL_ERROR,
            {"calculator_handler": failing_calculator},
        ),
    ],
)
def test_external_agent_tool_boundary_failures_are_observable(
    agent: object,
    expected_error: ErrorCode,
    registry_options: dict[str, object],
) -> None:
    result = ScenarioRunner(registry=build_registry(**registry_options)).run(
        agent, control_scenario()
    )

    assert result.error_code is expected_error
    assert result.tool_calls
    call = result.tool_calls[0]
    assert call.error_code is expected_error
    assert call.success is False
    if expected_error is ErrorCode.APPROVAL_REQUIRED:
        assert call.permission_allowed is False
        assert call.requires_approval is True
        assert call.executed is False
    elif expected_error is ErrorCode.TOOL_ERROR:
        assert call.permission_allowed is True
        assert call.executed is True
    else:
        assert call.executed is False
