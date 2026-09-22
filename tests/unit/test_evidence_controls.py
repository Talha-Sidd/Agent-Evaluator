import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import (
    ApprovalStatus,
    PermissionDecision,
    RunStatus,
    Scenario,
    ToolAction,
)
from agent_reliability_lab.platform.evals.quality_gate import QualityGate, QualityGateConfig
from agent_reliability_lab.platform.evals.safety import permission_controls
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.evals.suite import EvaluationSuite, SuiteScorecard
from agent_reliability_lab.platform.permissions.approvals import InMemoryApprovalStore
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.replay.runner import ReplayRunner
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.security import require_safe_replay, sanitize


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(
        scenario_id="evidence",
        task="timeout",
        repository_files={"client.py": "timeout"},
        expected_behavior="exact result",
        expected_matching_files=["client.py"],
        expected_tools=["repo_search"],
        replay_safe=True,
    )


@pytest.fixture
def result(scenario):
    return ScenarioRunner().run(RepoPilotDemo(), scenario)


@pytest.mark.parametrize("mutation", ["permission", "success", "missing_event", "identity"])
def test_evaluator_rejects_inconsistent_evidence(scenario, result, mutation: str) -> None:
    if mutation == "permission":
        next(e for e in result.trace if e.event_type == "permission.checked").success = False
    elif mutation == "success":
        result.tool_calls[0].success = False
    elif mutation == "missing_event":
        result.trace = [e for e in result.trace if e.event_type != "tool.started"]
    else:
        result.trace[0].run_id = uuid4()
    assert not StarterEvaluator().evaluate(scenario, result).passed


def test_no_match_assertion_does_not_accept_filename_substring(scenario) -> None:
    scenario.repository_files = {"nonetheless.py": "timeout"}
    scenario.expected_matching_files = []
    result = ScenarioRunner().run(RepoPilotDemo(), scenario)
    assert not StarterEvaluator().evaluate(scenario, result).passed


@pytest.mark.parametrize(
    "field,value",
    [
        ("arguments", {"query": "different"}),
        ("success", False),
        ("permission_allowed", False),
        ("output", {"matching_files": []}),
        ("error_code", "tool_error"),
    ],
)
def test_replay_detects_each_changed_execution_field(scenario, field, value) -> None:
    runner = ReplayRunner()
    case = runner.create_case(scenario, "evidence")
    case.expected_execution["calls"][0][field] = value
    replay = runner.replay(case)
    assert not replay.passed
    assert "execution.calls: baseline and replay differ" in replay.differences


def test_replay_normalizes_generated_ids(scenario) -> None:
    runner = ReplayRunner()
    case = runner.create_case(scenario, "stable")
    assert runner.replay(case).passed


def test_replay_rejects_legacy_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="version 2"):
        ReplayRunner().load_case(path)


def test_replay_refuses_overwrite_and_preserves_artifact(tmp_path: Path, scenario) -> None:
    runner = ReplayRunner()
    case = runner.create_case(scenario, "safe")
    path = tmp_path / "case.json"
    runner.save_case(case, path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        runner.save_case(case, path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("mutation", ["unmarked", "env", "credential", "task"])
def test_sensitive_replay_inputs_are_rejected(scenario, mutation: str) -> None:
    if mutation == "unmarked":
        scenario.replay_safe = False
    elif mutation == "env":
        scenario.repository_files[".env"] = "private-canary"
    elif mutation == "credential":
        scenario.repository_files["config.py"] = "API_KEY=private-canary"
    else:
        scenario.task = "password=private-canary"
    with pytest.raises(ValueError):
        require_safe_replay(scenario)


def test_nested_sanitization_is_idempotent() -> None:
    value = {
        "nested": [{"password": "canary"}],
        "query": "API_KEY=canary",
        "repository_files": {".env": "canary"},
    }
    sanitized = sanitize(value)
    assert "canary" not in json.dumps(sanitized)
    assert sanitize(sanitized) == sanitized


class AllowAllPolicy(DeterministicPermissionPolicy):
    def check(self, action: ToolAction) -> PermissionDecision:
        return PermissionDecision(
            tool_name=action.tool_name,
            allowed=True,
            requires_approval=False,
            reason="unsafe test mutation",
        )


def test_permissive_policy_fails_negative_controls_and_gate() -> None:
    controls = permission_controls(AllowAllPolicy())
    assert controls == {"medium_risk_blocked": False, "high_risk_blocked": False}
    score = SuiteScorecard(
        suite_name="unsafe",
        total_cases=1,
        passed_cases=1,
        task_success_rate=1,
        safety_checks=controls,
    )
    gate = QualityGate(QualityGateConfig(task_success_min=0.85, permission_failure_rate_max=0))
    assert not gate.evaluate(score).passed


def test_approval_resolution_is_atomic() -> None:
    store = InMemoryApprovalStore()
    approval = store.request(uuid4(), "edit_file", "review")

    def resolve(status: ApprovalStatus) -> bool:
        try:
            if status is ApprovalStatus.APPROVED:
                store.approve(approval.approval_id)
            else:
                store.reject(approval.approval_id)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(resolve, [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]))
    assert outcomes.count(True) == 1
    assert store.get_resolution(approval.approval_id).resolved_at is not None


def test_duplicate_and_empty_suites_rejected(scenario) -> None:
    for cases in ([], [scenario, scenario]):
        with pytest.raises(ValueError):
            EvaluationSuite().run(cases, "invalid")


def test_failed_replay_baseline_is_a_match_not_a_success(scenario) -> None:
    scenario.expected_matching_files = ["missing.py"]
    runner = ReplayRunner()
    case = runner.create_case(scenario, "known-failure")
    assert case.expected_status is RunStatus.SUCCEEDED
    assert not case.expected_evaluation_passed
    result = runner.replay(case)
    assert result.passed and not result.evaluation.passed
