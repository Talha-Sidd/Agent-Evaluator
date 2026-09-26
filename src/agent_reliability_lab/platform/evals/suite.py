"""Deterministic evaluation-suite execution and scorecard generation."""

import json
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import (
    AgentResult,
    EvaluationCheck,
    EvaluationResult,
    FailureCategory,
    FailureReport,
    Scenario,
)
from agent_reliability_lab.domain.protocols import AgentAdapter
from agent_reliability_lab.platform.evals.performance import SuiteLatency, summarize_latency
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.runner.runner import ScenarioRunner


class CaseReport(BaseModel):
    """Retained result and evaluation evidence for one suite scenario."""

    result: AgentResult
    evaluation: EvaluationResult


class SuiteScorecard(BaseModel):
    """Aggregate suite outcome with consistency checks and safety controls."""

    model_config = ConfigDict(extra="forbid")

    suite_name: str
    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: list[str] = Field(default_factory=list)
    failure_category_counts: dict[str, int] = Field(default_factory=dict)
    task_success_rate: float = Field(ge=0.0, le=1.0)
    cases: list[CaseReport] = Field(default_factory=list)
    safety_checks: dict[str, bool] = Field(default_factory=dict)
    latency: SuiteLatency | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.passed_cases + len(self.failed_cases) != self.total_cases:
            raise ValueError("inconsistent case counts")
        rate = self.passed_cases / self.total_cases if self.total_cases else 0.0
        if abs(rate - self.task_success_rate) > 1e-12:
            raise ValueError("inconsistent success rate")
        if len(set(self.failed_cases)) != len(self.failed_cases):
            raise ValueError("duplicate failed scenario IDs")
        if any(
            count < 0 or count > self.total_cases for count in self.failure_category_counts.values()
        ):
            raise ValueError("invalid failure case count")
        return self


class EvaluationSuite:
    """Run fixed scenarios with one deterministic agent and evaluator."""

    def __init__(
        self, agent: AgentAdapter | None = None, runner: ScenarioRunner | None = None
    ) -> None:
        self._runner = runner or ScenarioRunner()
        self._agent = agent or RepoPilotDemo()
        self._evaluator = StarterEvaluator()

    def load_jsonl(self, path: Path) -> list[Scenario]:
        scenarios: list[Scenario] = []
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("dataset exceeds 16 MiB")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                scenarios.append(Scenario.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                raise ValueError(f"invalid scenario at line {line_number}") from None
        self._validate_cases(scenarios)
        return scenarios

    def _validate_cases(self, scenarios: list[Scenario]) -> None:
        if not scenarios or len(scenarios) > 1000:
            raise ValueError("suite must contain between 1 and 1000 cases")
        if len({scenario.scenario_id for scenario in scenarios}) != len(scenarios):
            raise ValueError("duplicate scenario IDs")

    def run(self, scenarios: list[Scenario], suite_name: str) -> SuiteScorecard:
        self._validate_cases(scenarios)
        evaluations: list[EvaluationResult] = []
        cases: list[CaseReport] = []
        for scenario in scenarios:
            result = self._runner.run(self._agent, scenario)
            try:
                evaluation = self._evaluator.evaluate(scenario, result)
            except Exception:  # noqa: BLE001 -- one failed grader must not erase the suite
                evaluation = EvaluationResult(
                    scenario_id=scenario.scenario_id,
                    passed=False,
                    checks=[
                        EvaluationCheck(name="evaluator", passed=False, detail="evaluation_failure")
                    ],
                    failure_reports=[
                        FailureReport(
                            category=FailureCategory.GRADER_EVALUATION_FAILURE,
                            evidence_event_ids=[event.event_id for event in result.trace],
                            confidence=1.0,
                            likely_fix="Repair the evaluator before trusting this run.",
                        )
                    ],
                )
            evaluations.append(evaluation)
            cases.append(CaseReport(result=result, evaluation=evaluation))

        passed_cases = sum(evaluation.passed for evaluation in evaluations)
        failed_cases = [
            evaluation.scenario_id for evaluation in evaluations if not evaluation.passed
        ]
        failure_category_counts: dict[str, int] = {}
        for evaluation in evaluations:
            for category in {report.category.value for report in evaluation.failure_reports}:
                failure_category_counts[category] = failure_category_counts.get(category, 0) + 1
        total_cases = len(evaluations)
        success_rate = passed_cases / total_cases if total_cases else 0.0
        return SuiteScorecard(
            suite_name=suite_name,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            failure_category_counts=failure_category_counts,
            task_success_rate=success_rate,
            cases=cases,
            safety_checks=self._runner.safety_controls(),
            latency=summarize_latency([case.result for case in cases]),
        )
