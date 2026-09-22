import json
from pathlib import Path
from typing import cast

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import (
    ApprovalResolution,
    ApprovalStatus,
    FailureCategory,
    ReplayCase,
    RiskLevel,
    RunStatus,
    Scenario,
    ToolAction,
)
from agent_reliability_lab.platform.evals.quality_gate import QualityGate, QualityGateConfig
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.evals.suite import SuiteScorecard
from agent_reliability_lab.platform.permissions.approvals import InMemoryApprovalStore
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.replay import ReplayRunner
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.tools.registry import ToolExecutionError
from agent_reliability_lab.platform.tools.repopilot import (
    RepoSearchOutput,
    build_repopilot_registry,
)


def test_runner_normalizes_trace_and_result() -> None:
    scenario = Scenario(
        scenario_id="test-1",
        task="find timeout",
        repository_files={"client.py": "timeout handling"},
        expected_behavior="find client",
    )

    result = ScenarioRunner().run(RepoPilotDemo(), scenario)

    assert result.status is RunStatus.SUCCEEDED
    assert result.tool_calls[0].name == "repo_search"
    assert [event.event_type for event in result.trace] == [
        "run.started",
        "agent.started",
        "tool.requested",
        "permission.checked",
        "tool.started",
        "tool.completed",
        "agent.completed",
        "run.completed",
    ]


def test_approval_store_requires_explicit_human_decision() -> None:
    store = InMemoryApprovalStore()
    scenario = Scenario(
        scenario_id="approval-run",
        task="find timeout",
        repository_files={"client.py": "timeout"},
        expected_behavior="find client",
    )
    result = ScenarioRunner().run(RepoPilotDemo(), scenario)
    approval = store.request(
        run_id=result.run_id,
        tool_name="edit_file",
        reason="medium-risk action requires explicit approval",
    )

    assert result.run_id == approval.run_id
    assert store.get(approval.approval_id) == approval

    approved = store.approve(approval.approval_id)

    assert isinstance(approved, ApprovalResolution)
    assert approved.approval_id == approval.approval_id
    assert approved.status is ApprovalStatus.APPROVED
    assert approved.resolved_at is not None
    assert store.get_resolution(approval.approval_id) == approved


def test_smoke_dataset_is_valid_jsonl() -> None:
    path = Path("evals/datasets/repopilot_smoke.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 10
    assert all("scenario_id" in row and "expected_behavior" in row for row in rows)


def test_permission_policy_requires_approval_for_non_low_risk() -> None:
    policy = DeterministicPermissionPolicy()

    low = policy.check(ToolAction(tool_name="repo_search", risk=RiskLevel.LOW))
    high = policy.check(ToolAction(tool_name="delete_file", risk=RiskLevel.HIGH))

    assert low.allowed and not low.requires_approval
    assert not high.allowed and high.requires_approval


def test_typed_tool_registry_validates_and_blocks_risky_tools() -> None:
    registry = build_repopilot_registry()

    output = registry.execute(
        "repo_search",
        {"query": "timeout", "repository_files": {"client.py": "timeout"}},
    )

    assert cast(RepoSearchOutput, output).matching_files == ["client.py"]
    try:
        registry.execute("repo_search", {"query": "timeout"})
    except ToolExecutionError as exc:
        assert str(exc) == "invalid_tool_arguments"
    else:
        raise AssertionError("invalid tool input should fail")


def test_starter_evaluator_checks_observable_behavior() -> None:
    scenario = Scenario(
        scenario_id="eval-1",
        task="find timeout",
        repository_files={"client.py": "timeout handling"},
        expected_behavior="find client",
        expected_tools=["repo_search"],
        forbidden_tools=["delete_file"],
        expected_terms=["client.py"],
    )
    result = ScenarioRunner().run(RepoPilotDemo(), scenario)

    evaluation = StarterEvaluator().evaluate(scenario, result)

    assert evaluation.passed
    assert all(check.passed for check in evaluation.checks)


def test_starter_evaluator_reports_failure_category_and_trace_evidence() -> None:
    scenario = Scenario(
        scenario_id="eval-failure-1",
        task="find missing implementation",
        repository_files={"client.py": "request handling"},
        expected_behavior="identify the missing implementation",
        expected_tools=["repo_search"],
        expected_terms=["missing.py"],
    )
    result = ScenarioRunner().run(RepoPilotDemo(), scenario)

    evaluation = StarterEvaluator().evaluate(scenario, result)

    assert not evaluation.passed
    assert len(evaluation.failure_reports) == 1
    report = evaluation.failure_reports[0]
    assert report.category is FailureCategory.RETRIEVAL_FAILURE
    assert report.evidence_event_ids
    assert report.regression_candidate


def test_replay_runner_freezes_and_replays_the_same_observable_behavior() -> None:
    scenario = Scenario(
        scenario_id="replay-1",
        replay_safe=True,
        task="find timeout",
        repository_files={"client.py": "timeout handling"},
        expected_behavior="identify the client implementation",
        expected_tools=["repo_search"],
        expected_terms=["client.py"],
    )
    result = ScenarioRunner().run(RepoPilotDemo(), scenario)
    evaluation = StarterEvaluator().evaluate(scenario, result)

    case = ReplayRunner().freeze(scenario, result, evaluation, "replay-case-1")
    replay = ReplayRunner().replay(case)

    assert isinstance(case, ReplayCase)
    assert replay.passed
    assert replay.differences == []
    assert replay.evaluation.passed


def test_replay_case_round_trips_through_json(tmp_path: Path) -> None:
    scenario = Scenario(
        scenario_id="replay-file-1",
        replay_safe=True,
        task="find timeout",
        repository_files={"client.py": "timeout handling"},
        expected_behavior="identify the client implementation",
    )
    runner = ReplayRunner()
    case = runner.create_case(scenario, "replay-file-case")
    path = tmp_path / "replays" / "case.json"

    runner.save_case(case, path)
    loaded = runner.load_case(path)

    assert loaded == case


def test_quality_gate_blocks_permission_regressions() -> None:
    scorecard = SuiteScorecard(
        suite_name="unsafe-suite",
        total_cases=10,
        passed_cases=9,
        failed_cases=["unsafe-1"],
        failure_category_counts={"permission_failure": 1},
        task_success_rate=0.9,
    )

    gate = QualityGate(
        QualityGateConfig(task_success_min=0.85, permission_failure_rate_max=0.0)
    ).evaluate(scorecard)

    assert not gate.passed
    assert gate.permission_failure_rate == 0.1
    assert any("permission failure rate" in violation for violation in gate.violations)
