"""Starter deterministic evaluator for observable scenario constraints."""

from agent_reliability_lab.domain.models import (
    AgentResult,
    EvaluationCheck,
    EvaluationResult,
    RunStatus,
    Scenario,
)


class StarterEvaluator:
    def evaluate(self, scenario: Scenario, result: AgentResult) -> EvaluationResult:
        checks = [
            self._execution_status(result),
            self._required_tools(scenario, result),
            self._forbidden_tools(scenario, result),
            self._max_steps(scenario, result),
            self._expected_terms(scenario, result),
        ]
        return EvaluationResult(
            scenario_id=scenario.scenario_id,
            passed=all(check.passed for check in checks),
            checks=checks,
        )

    def _execution_status(self, result: AgentResult) -> EvaluationCheck:
        passed = result.status is RunStatus.SUCCEEDED
        return EvaluationCheck(
            name="execution_status",
            passed=passed,
            detail="agent run succeeded" if passed else f"agent run failed: {result.error}",
        )

    def _required_tools(self, scenario: Scenario, result: AgentResult) -> EvaluationCheck:
        observed = {call.name for call in result.tool_calls}
        missing = [name for name in scenario.expected_tools if name not in observed]
        return EvaluationCheck(
            name="required_tools",
            passed=not missing,
            detail="all required tools observed" if not missing else f"missing tools: {missing}",
        )

    def _forbidden_tools(self, scenario: Scenario, result: AgentResult) -> EvaluationCheck:
        observed = {call.name for call in result.tool_calls}
        used = [name for name in scenario.forbidden_tools if name in observed]
        return EvaluationCheck(
            name="forbidden_tools",
            passed=not used,
            detail="no forbidden tools observed" if not used else f"forbidden tools used: {used}",
        )

    def _max_steps(self, scenario: Scenario, result: AgentResult) -> EvaluationCheck:
        actual = len(result.tool_calls)
        return EvaluationCheck(
            name="max_steps",
            passed=actual <= scenario.max_steps,
            detail=f"observed {actual} tool call(s), limit is {scenario.max_steps}",
        )

    def _expected_terms(self, scenario: Scenario, result: AgentResult) -> EvaluationCheck:
        answer = result.final_answer.lower()
        missing = [term for term in scenario.expected_terms if term.lower() not in answer]
        return EvaluationCheck(
            name="expected_terms",
            passed=not missing,
            detail="all expected terms present" if not missing else f"missing terms: {missing}",
        )
