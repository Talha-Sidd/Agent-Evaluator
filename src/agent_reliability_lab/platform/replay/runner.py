"""Freeze and replay deterministic runs for regression testing."""

from pathlib import Path

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import (
    AgentResult,
    EvaluationResult,
    ReplayCase,
    ReplayResult,
    Scenario,
)
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.runner.runner import ScenarioRunner


class ReplayRunner:
    """Create replay cases from evidence and compare future executions."""

    def __init__(self) -> None:
        self._runner = ScenarioRunner()
        self._agent = RepoPilotDemo()
        self._evaluator = StarterEvaluator()

    def freeze(
        self,
        scenario: Scenario,
        result: AgentResult,
        evaluation: EvaluationResult,
        case_id: str,
    ) -> ReplayCase:
        return ReplayCase(
            case_id=case_id,
            baseline_run_id=result.run_id,
            scenario=scenario.model_copy(deep=True),
            expected_status=result.status,
            expected_final_answer=result.final_answer,
            expected_tool_names=[call.name for call in result.tool_calls],
            expected_trace_event_types=[event.event_type for event in result.trace],
            expected_evaluation_passed=evaluation.passed,
        )

    def create_case(self, scenario: Scenario, case_id: str) -> ReplayCase:
        """Run a scenario once and freeze its observable baseline."""

        result = self._runner.run(self._agent, scenario)
        evaluation = self._evaluator.evaluate(scenario, result)
        return self.freeze(scenario, result, evaluation, case_id)

    def save_case(self, case: ReplayCase, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(case.model_dump_json(indent=2), encoding="utf-8")

    def load_case(self, path: Path) -> ReplayCase:
        return ReplayCase.model_validate_json(path.read_text(encoding="utf-8"))

    def replay(self, case: ReplayCase) -> ReplayResult:
        result = self._runner.run(self._agent, case.scenario)
        evaluation = self._evaluator.evaluate(case.scenario, result)
        differences: list[str] = []
        actual_tool_names = [call.name for call in result.tool_calls]
        actual_trace_event_types = [event.event_type for event in result.trace]
        comparisons = [
            ("status", case.expected_status, result.status),
            ("final_answer", case.expected_final_answer, result.final_answer),
            ("tool_names", case.expected_tool_names, actual_tool_names),
            ("trace_event_types", case.expected_trace_event_types, actual_trace_event_types),
            ("evaluation_passed", case.expected_evaluation_passed, evaluation.passed),
        ]
        for name, expected, actual in comparisons:
            if expected != actual:
                differences.append(f"{name}: expected {expected!r}, got {actual!r}")
        return ReplayResult(
            case_id=case.case_id,
            replay_run_id=result.run_id,
            passed=not differences,
            differences=differences,
            evaluation=evaluation,
        )
