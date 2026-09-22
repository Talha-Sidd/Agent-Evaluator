"""Deterministic evaluation-suite execution and scorecard generation."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import EvaluationResult, Scenario
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.runner.runner import ScenarioRunner


class SuiteScorecard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: str
    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: list[str] = Field(default_factory=list)
    task_success_rate: float = Field(ge=0.0, le=1.0)


class EvaluationSuite:
    """Run fixed scenarios with one deterministic agent and evaluator."""

    def __init__(self) -> None:
        self._runner = ScenarioRunner()
        self._agent = RepoPilotDemo()
        self._evaluator = StarterEvaluator()

    def load_jsonl(self, path: Path) -> list[Scenario]:
        scenarios: list[Scenario] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                scenarios.append(Scenario.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid scenario at {path}:{line_number}: {exc}") from exc
        return scenarios

    def run(self, scenarios: list[Scenario], suite_name: str) -> SuiteScorecard:
        evaluations: list[EvaluationResult] = []
        for scenario in scenarios:
            result = self._runner.run(self._agent, scenario)
            evaluations.append(self._evaluator.evaluate(scenario, result))

        passed_cases = sum(evaluation.passed for evaluation in evaluations)
        failed_cases = [
            evaluation.scenario_id for evaluation in evaluations if not evaluation.passed
        ]
        total_cases = len(evaluations)
        success_rate = passed_cases / total_cases if total_cases else 0.0
        return SuiteScorecard(
            suite_name=suite_name,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            task_success_rate=success_rate,
        )
