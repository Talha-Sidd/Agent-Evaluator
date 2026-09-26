"""Compact evaluation snapshots and deterministic baseline comparison.

Snapshots are local, trusted evaluation artifacts, not signed attestations. They
exclude task text, fixture content, answers, and raw tool arguments.
"""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_reliability_lab.domain.models import FailureCategory, Scenario
from agent_reliability_lab.platform.evals.quality_gate import (
    QualityGate,
    QualityGateConfig,
    QualityGateResult,
)
from agent_reliability_lab.platform.evals.suite import SuiteScorecard
from agent_reliability_lab.platform.security import fingerprint, sanitize

# Bump when grading semantics change; comparisons across versions are rejected.
EVALUATOR_VERSION = "starter-v2"
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\w./:@+-]+$")]


class CaseSnapshot(BaseModel):
    """One outcome and its input identity; aggregates are derived, never trusted."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=128)
    scenario_sha256: Digest
    fixture_sha256: Digest
    run_id: UUID
    passed: bool = Field(strict=True)
    failure_categories: list[FailureCategory] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if len(set(self.failure_categories)) != len(self.failure_categories):
            raise ValueError("duplicate failure categories")
        if self.passed and self.failure_categories:
            raise ValueError("passing cases cannot contain failures")
        return self


class EvaluationSnapshot(BaseModel):
    """Versioned, bounded artifact suitable for comparing separate checkouts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    agent_version: Label
    evaluator_version: Label = EVALUATOR_VERSION
    dataset_sha256: Digest
    cases: list[CaseSnapshot] = Field(min_length=1, max_length=1000)
    safety_checks: dict[Label, Annotated[bool, Field(strict=True)]] = Field(max_length=32)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        identities = {case.scenario_id: case.scenario_sha256 for case in self.cases}
        if len(identities) != len(self.cases):
            raise ValueError("duplicate scenario IDs")
        if fingerprint(identities) != self.dataset_sha256:
            raise ValueError("inconsistent dataset fingerprint")
        if sanitize(self.model_dump(mode="json")) != self.model_dump(mode="json"):
            raise ValueError("snapshot metadata contains sensitive text")
        return self

    def scorecard(self) -> SuiteScorecard:
        failed = [case.scenario_id for case in self.cases if not case.passed]
        counts: dict[str, int] = {}
        for case in self.cases:
            for category in case.failure_categories:
                counts[category.value] = counts.get(category.value, 0) + 1
        return SuiteScorecard(
            suite_name="snapshot",
            total_cases=len(self.cases),
            passed_cases=len(self.cases) - len(failed),
            failed_cases=failed,
            failure_category_counts=counts,
            task_success_rate=(len(self.cases) - len(failed)) / len(self.cases),
            safety_checks=self.safety_checks,
        )


def create_snapshot(
    scenarios: list[Scenario], scorecard: SuiteScorecard, agent_version: str
) -> EvaluationSnapshot:
    """Capture a suite run without exporting its raw inputs or agent output."""
    inputs = {scenario.scenario_id: scenario for scenario in scenarios}
    if len(inputs) != len(scenarios) or len(scorecard.cases) != len(inputs):
        raise ValueError("snapshot requires complete, unique case evidence")
    cases: list[CaseSnapshot] = []
    for report in scorecard.cases:
        evaluation = report.evaluation
        scenario = inputs.get(evaluation.scenario_id)
        if scenario is None or report.result.scenario_id != evaluation.scenario_id:
            raise ValueError("snapshot evidence does not match dataset")
        cases.append(
            CaseSnapshot(
                scenario_id=scenario.scenario_id,
                scenario_sha256=fingerprint(scenario.model_dump(mode="json")),
                fixture_sha256=fingerprint(scenario.repository_files),
                run_id=report.result.run_id,
                passed=evaluation.passed,
                failure_categories=sorted(
                    {report.category for report in evaluation.failure_reports},
                    key=lambda category: category.value,
                ),
            )
        )
    return EvaluationSnapshot(
        agent_version=agent_version,
        dataset_sha256=fingerprint({case.scenario_id: case.scenario_sha256 for case in cases}),
        cases=cases,
        safety_checks=scorecard.safety_checks,
    )


class ComparisonResult(BaseModel):
    """Per-case changes plus absolute and regression gate decisions."""

    baseline_version: str
    candidate_version: str
    dataset_sha256: str
    baseline_success_rate: float
    candidate_success_rate: float
    success_rate_delta: float
    regressions: list[str]
    improvements: list[str]
    unchanged_cases: list[str]
    regression_rate: float
    candidate_gate: QualityGateResult
    violations: list[str]
    passed: bool


def compare_snapshots(
    baseline: EvaluationSnapshot, candidate: EvaluationSnapshot, config: QualityGateConfig
) -> ComparisonResult:
    baseline = EvaluationSnapshot.model_validate(baseline.model_dump())
    candidate = EvaluationSnapshot.model_validate(candidate.model_dump())
    config = QualityGateConfig.model_validate(config.model_dump())
    if (
        baseline.dataset_sha256 != candidate.dataset_sha256
        or baseline.evaluator_version != candidate.evaluator_version
    ):
        raise ValueError("comparison requires identical dataset and evaluator versions")
    before = {case.scenario_id: case for case in baseline.cases}
    after = {case.scenario_id: case for case in candidate.cases}
    if before.keys() != after.keys() or any(
        before[key].fixture_sha256 != after[key].fixture_sha256 for key in before
    ):
        raise ValueError("comparison requires identical cases and fixtures")
    regressions = sorted(key for key in before if before[key].passed and not after[key].passed)
    improvements = sorted(key for key in before if not before[key].passed and after[key].passed)
    unchanged = sorted(key for key in before if before[key].passed == after[key].passed)
    old_score = baseline.scorecard()
    new_score = candidate.scorecard()
    gate = QualityGate(config).evaluate(new_score)
    regression_rate = len(regressions) / len(before)
    violations = list(gate.violations)
    if regression_rate > config.regression_tolerance:
        violations.append(
            f"regression rate {regression_rate:.3f} exceeds maximum "
            f"{config.regression_tolerance:.3f}"
        )
    return ComparisonResult(
        baseline_version=baseline.agent_version,
        candidate_version=candidate.agent_version,
        dataset_sha256=candidate.dataset_sha256,
        baseline_success_rate=old_score.task_success_rate,
        candidate_success_rate=new_score.task_success_rate,
        success_rate_delta=new_score.task_success_rate - old_score.task_success_rate,
        regressions=regressions,
        improvements=improvements,
        unchanged_cases=unchanged,
        regression_rate=regression_rate,
        candidate_gate=gate,
        violations=violations,
        passed=not violations,
    )


def save_snapshot(snapshot: EvaluationSnapshot, path: Path) -> None:
    """Atomically publish a new artifact; never overwrite an existing baseline."""
    snapshot = EvaluationSnapshot.model_validate(snapshot.model_dump())
    encoded = (snapshot.model_dump_json(indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds 4 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_snapshot(path: Path) -> EvaluationSnapshot:
    if path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds 4 MiB")
    # Pydantic's JSON parser bounds nesting and normalizes malformed JSON to
    # ValidationError, including input that would overflow json.loads recursion.
    return EvaluationSnapshot.model_validate_json(path.read_bytes())
