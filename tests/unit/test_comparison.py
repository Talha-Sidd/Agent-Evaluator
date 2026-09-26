import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent_reliability_lab.domain.models import FailureCategory
from agent_reliability_lab.platform.evals.comparison import (
    CaseSnapshot,
    EvaluationSnapshot,
    compare_snapshots,
    load_snapshot,
    save_snapshot,
)
from agent_reliability_lab.platform.evals.quality_gate import QualityGateConfig
from agent_reliability_lab.platform.security import fingerprint


def snapshot(outcomes: list[bool], version: str = "v1") -> EvaluationSnapshot:
    cases = [
        CaseSnapshot(
            scenario_id=f"case-{index}",
            scenario_sha256=fingerprint(index),
            fixture_sha256=fingerprint({"file": index}),
            run_id=uuid4(),
            passed=passed,
            failure_categories=[] if passed else [FailureCategory.RETRIEVAL_FAILURE],
        )
        for index, passed in enumerate(outcomes)
    ]
    return EvaluationSnapshot(
        agent_version=version,
        dataset_sha256=fingerprint({case.scenario_id: case.scenario_sha256 for case in cases}),
        cases=cases,
        safety_checks={"medium_risk_blocked": True, "high_risk_blocked": True},
    )


def config(tolerance: float = 0.0) -> QualityGateConfig:
    return QualityGateConfig(
        task_success_min=0.5, permission_failure_rate_max=0.0,
        regression_tolerance=tolerance,
    )


def test_improvements_cannot_hide_regressions() -> None:
    result = compare_snapshots(snapshot([True, False]), snapshot([False, True], "v2"), config())
    assert result.success_rate_delta == 0
    assert result.regressions == ["case-0"]
    assert result.improvements == ["case-1"]
    assert result.candidate_gate.passed
    assert not result.passed
    assert result.regression_rate == 0.5


def test_tolerance_boundary_and_order_independent_comparison() -> None:
    baseline, candidate = snapshot([True, False]), snapshot([False, True])
    candidate.cases.reverse()
    assert compare_snapshots(baseline, candidate, config(0.5)).passed
    assert not compare_snapshots(baseline, candidate, config(0.499)).passed


@pytest.mark.parametrize("control", ["medium_risk_blocked", "high_risk_blocked"])
def test_safety_controls_block_even_perfect_candidate(control: str) -> None:
    candidate = snapshot([True, True])
    candidate.safety_checks.pop(control)
    assert not compare_snapshots(snapshot([True, True]), candidate, config(1)).passed


def test_permission_failure_blocks_candidate_within_regression_tolerance() -> None:
    candidate = snapshot([True, False])
    candidate.cases[1].failure_categories = [FailureCategory.PERMISSION_FAILURE]
    result = compare_snapshots(snapshot([True, True]), candidate, config(1))
    assert not result.passed
    assert result.candidate_gate.permission_failure_rate == 0.5


def test_unchanged_failed_baseline_does_not_bypass_absolute_gate() -> None:
    result = compare_snapshots(snapshot([False, False]), snapshot([False, False]), config())
    assert result.regressions == []
    assert not result.passed


@pytest.mark.parametrize("change", ["dataset", "fixture", "evaluator", "missing_case"])
def test_incompatible_snapshots_are_rejected(change: str) -> None:
    baseline, candidate = snapshot([True, True]), snapshot([True, True])
    if change == "dataset":
        candidate.cases[0].scenario_sha256 = fingerprint("changed task or expectations")
    elif change == "fixture":
        candidate.cases[0].fixture_sha256 = fingerprint("changed fixture")
    elif change == "evaluator":
        candidate.evaluator_version = "starter-v3"
    else:
        candidate.cases.pop()
    candidate.dataset_sha256 = fingerprint(
        {case.scenario_id: case.scenario_sha256 for case in candidate.cases}
    )
    with pytest.raises(ValueError):
        compare_snapshots(baseline, candidate, config())


@pytest.mark.parametrize("change", ["duplicate", "empty", "hash", "boolean", "version", "secret"])
def test_malformed_artifacts_fail_closed(tmp_path: Path, change: str) -> None:
    value = snapshot([True]).model_dump(mode="json")
    if change == "duplicate":
        value["cases"].append(value["cases"][0])
    elif change == "empty":
        value["cases"] = []
    elif change == "hash":
        value["dataset_sha256"] = "0" * 64
    elif change == "boolean":
        value["cases"][0]["passed"] = "true"
    elif change == "version":
        value["schema_version"] = 2
    else:
        value["cases"][0]["scenario_id"] = "api_key=private-canary"
        value["dataset_sha256"] = fingerprint(
            {case["scenario_id"]: case["scenario_sha256"] for case in value["cases"]}
        )
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        load_snapshot(path)


def test_snapshot_roundtrip_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    original = snapshot([True, False])
    save_snapshot(original, path)
    assert load_snapshot(path) == original
    with pytest.raises(FileExistsError):
        save_snapshot(snapshot([False, True]), path)
    assert load_snapshot(path) == original
    assert list(tmp_path.iterdir()) == [path]


def test_oversized_snapshot_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    with path.open("wb") as file:
        file.truncate(4 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="4 MiB"):
        load_snapshot(path)


@pytest.mark.parametrize("checks", [{"x" * 129: True}, {str(i): True for i in range(33)}])
def test_unbounded_metadata_cannot_publish_an_artifact(tmp_path: Path, checks) -> None:
    artifact = snapshot([True])
    artifact.safety_checks = checks
    with pytest.raises(ValueError):
        save_snapshot(artifact, tmp_path / "invalid.json")
    assert list(tmp_path.iterdir()) == []
