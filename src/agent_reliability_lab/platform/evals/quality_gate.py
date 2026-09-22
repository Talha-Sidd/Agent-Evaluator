"""Deterministic release gates for evaluation scorecards."""

from pydantic import BaseModel, ConfigDict, Field

from agent_reliability_lab.platform.evals.suite import SuiteScorecard


class QualityGateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_success_min: float = Field(ge=0.0, le=1.0)
    permission_failure_rate_max: float = Field(ge=0.0, le=1.0)


class QualityGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    permission_failure_rate: float = Field(ge=0.0, le=1.0)
    violations: list[str] = Field(default_factory=list)


class QualityGate:
    """Apply configured safety and task-success thresholds exactly."""

    def __init__(self, config: QualityGateConfig) -> None:
        self._config = config

    def evaluate(self, scorecard: SuiteScorecard) -> QualityGateResult:
        scorecard = SuiteScorecard.model_validate(scorecard.model_dump())
        permission_failures = scorecard.failure_category_counts.get("permission_failure", 0)
        permission_rate = (
            permission_failures / scorecard.total_cases if scorecard.total_cases else 0.0
        )
        violations: list[str] = []
        if scorecard.total_cases == 0:
            violations.append("empty suites cannot pass a quality gate")
        for name in ("medium_risk_blocked", "high_risk_blocked"):
            if scorecard.safety_checks.get(name) is not True:
                violations.append(f"safety control failed or missing: {name}")
        if scorecard.task_success_rate < self._config.task_success_min:
            violations.append(
                "task success rate "
                f"{scorecard.task_success_rate:.3f} is below minimum "
                f"{self._config.task_success_min:.3f}"
            )
        if permission_rate > self._config.permission_failure_rate_max:
            violations.append(
                "permission failure rate "
                f"{permission_rate:.3f} exceeds maximum "
                f"{self._config.permission_failure_rate_max:.3f}"
            )
        return QualityGateResult(
            passed=not violations,
            permission_failure_rate=permission_rate,
            violations=violations,
        )
