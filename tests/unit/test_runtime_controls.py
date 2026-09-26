"""Exercise real worker isolation with bounded, importable fixtures."""

import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from agent_reliability_lab.domain.errors import ToolExecutionError
from agent_reliability_lab.domain.models import (
    AgentResult,
    AgentTask,
    ErrorCode,
    RiskLevel,
    RunStatus,
    Scenario,
)
from agent_reliability_lab.domain.protocols import ToolExecutor
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.evals.suite import EvaluationSuite
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.tools.registry import ToolDefinition, TypedToolRegistry


@dataclass
class ProbeAgent:
    mode: str
    name = "probe"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        if self.mode == "crash":
            raise RuntimeError("API_KEY=private-error-canary")
        if self.mode == "hang":
            time.sleep(30)
        if self.mode == "identity":
            run_id = uuid4()
        if self.mode == "labels":
            assert not hasattr(task, "expected_terms")
            assert not hasattr(task, "forbidden_tools")
        if self.mode == "invalid":
            tools.execute("repo_search", {"repository_files": task.repository_files})
        if self.mode == "unknown":
            tools.execute("missing", {})
        if self.mode == "budget":
            for _ in range(3):
                tools.execute("repo_search", {"query": task.task, "repository_files": {}})
        if self.mode == "blocked":
            try:
                tools.execute("sentinel", {"path": task.task})
            except ToolExecutionError as exc:
                assert exc.code is ErrorCode.APPROVAL_REQUIRED
        if self.mode == "slowtool":
            tools.execute("sentinel", {"path": task.task})
        return AgentResult(
            run_id=run_id,
            scenario_id=task.scenario_id,
            status=RunStatus.SUCCEEDED,
            final_answer="done",
        )


class MarkerInput(BaseModel):
    path: str


def marker(payload: MarkerInput) -> MarkerInput:
    Path(payload.path).write_text("executed", encoding="utf-8")
    return payload


def delayed_marker(payload: MarkerInput) -> MarkerInput:
    time.sleep(2)
    return marker(payload)


def registry_with_marker(risk: RiskLevel, timeout: float = 5) -> TypedToolRegistry:
    registry = TypedToolRegistry(DeterministicPermissionPolicy())
    registry.register(
        ToolDefinition(
            name="sentinel",
            risk=risk,
            input_model=MarkerInput,
            output_model=MarkerInput,
            handler=delayed_marker if timeout < 2 else marker,
            timeout_seconds=timeout,
        )
    )
    return registry


@pytest.mark.parametrize(
    "mode,code",
    [
        ("crash", ErrorCode.INTERNAL_ERROR),
        ("identity", ErrorCode.INTERNAL_ERROR),
        ("invalid", ErrorCode.INVALID_TOOL_ARGUMENTS),
        ("unknown", ErrorCode.TOOL_NOT_FOUND),
        ("budget", ErrorCode.STEP_LIMIT_EXCEEDED),
    ],
)
def test_failures_have_identity_evidence_and_terminal_events(mode: str, code: ErrorCode) -> None:
    scenario = Scenario(
        scenario_id="failure", task="timeout", expected_behavior="bounded", max_steps=1
    )
    result = ScenarioRunner().run(ProbeAgent(mode), scenario)
    assert result.status is RunStatus.FAILED
    assert result.error_code is code
    assert all(event.run_id == result.run_id for event in result.trace)
    assert result.scenario_id == scenario.scenario_id
    assert [e.event_type for e in result.trace][-2:] == ["agent.completed", "run.completed"]
    assert sum(e.event_type == "run.completed" for e in result.trace) == 1
    assert "private-error-canary" not in result.model_dump_json()
    if mode == "budget":
        assert sum(call.executed for call in result.tool_calls) == 1


def test_hung_adapter_is_stopped() -> None:
    scenario = Scenario(
        scenario_id="timeout", task="timeout", expected_behavior="bounded", timeout_seconds=0.5
    )
    result = ScenarioRunner().run(ProbeAgent("hang"), scenario)
    assert result.error_code is ErrorCode.TIMEOUT
    assert result.trace[-1].event_type == "run.completed"


def test_hung_tool_is_stopped_before_late_side_effect(tmp_path: Path) -> None:
    path = tmp_path / "must-not-exist"
    scenario = Scenario(scenario_id="timeout", task=str(path), expected_behavior="bounded")
    result = ScenarioRunner(registry_with_marker(RiskLevel.LOW, 0.5)).run(
        ProbeAgent("slowtool"),
        scenario,
    )
    assert result.error_code is ErrorCode.TIMEOUT
    time.sleep(2.1)
    assert not path.exists()


@pytest.mark.parametrize("risk", [RiskLevel.MEDIUM, RiskLevel.HIGH])
def test_denied_handler_never_runs_and_blocked_attempt_is_not_a_breach(
    tmp_path: Path,
    risk: RiskLevel,
) -> None:
    path = tmp_path / "must-not-exist"
    scenario = Scenario(
        scenario_id="blocked",
        task=str(path),
        expected_behavior="blocked",
        forbidden_tools=["sentinel"],
    )
    result = ScenarioRunner(registry_with_marker(risk)).run(ProbeAgent("blocked"), scenario)
    assert result.status is RunStatus.SUCCEEDED
    assert not result.tool_calls[0].executed
    assert result.tool_calls[0].error_code is ErrorCode.APPROVAL_REQUIRED
    assert not path.exists()
    assert StarterEvaluator().evaluate(scenario, result).passed


def test_agent_cannot_see_grading_labels() -> None:
    scenario = Scenario(
        scenario_id="labels",
        task="timeout",
        expected_behavior="private label",
        expected_terms=["grader-only-answer"],
    )
    result = ScenarioRunner().run(ProbeAgent("labels"), scenario)
    assert result.status is RunStatus.SUCCEEDED
    assert result.timing is not None
    assert result.timing.source == "parent_monotonic"
    assert result.timing.agent_worker_startup_ms is not None
    assert result.timing.run_duration_ms >= result.timing.agent_worker_startup_ms


def test_suite_preserves_crash_evidence_and_continues() -> None:
    cases = [
        Scenario(scenario_id=str(i), task="timeout", expected_behavior="fail") for i in range(2)
    ]
    score = EvaluationSuite(agent=ProbeAgent("crash")).run(cases, "crashes")
    assert score.total_cases == 2 and score.passed_cases == 0
    assert len(score.cases) == 2
    for case in score.cases:
        ids = {event.event_id for event in case.result.trace}
        assert all(
            set(report.evidence_event_ids) <= ids for report in case.evaluation.failure_reports
        )


def test_argument_failure_is_not_reported_as_retrieval_failure() -> None:
    scenario = Scenario(
        scenario_id="bad-args",
        task="timeout",
        expected_behavior="fail",
        expected_terms=["missing.py"],
    )
    result = ScenarioRunner().run(ProbeAgent("invalid"), scenario)
    evaluation = StarterEvaluator().evaluate(scenario, result)
    assert {r.category.value for r in evaluation.failure_reports} == {"tool_argument_failure"}
    assert next(c for c in evaluation.checks if c.name == "expected_terms").skipped


def test_invalid_mutated_scenario_has_structured_failure() -> None:
    scenario = Scenario(scenario_id="invalid", task="timeout", expected_behavior="fail")
    scenario.task = ""
    result = ScenarioRunner().run(ProbeAgent("labels"), scenario)
    assert result.error_code is ErrorCode.INVALID_INPUT
    assert result.trace[-1].event_type == "run.completed"


def test_unhandled_approval_request_is_blocked_not_a_permission_breach(tmp_path: Path) -> None:
    scenario = Scenario(
        scenario_id="blocked", task=str(tmp_path / "never"), expected_behavior="fail"
    )
    result = ScenarioRunner(registry_with_marker(RiskLevel.HIGH)).run(
        ProbeAgent("slowtool"), scenario
    )
    evaluation = StarterEvaluator().evaluate(scenario, result)
    assert {r.category.value for r in evaluation.failure_reports} == {"policy_blocked"}
