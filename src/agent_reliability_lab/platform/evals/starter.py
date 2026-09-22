"""Starter deterministic evaluator for observable scenario constraints."""

from agent_reliability_lab.domain.models import (
    AgentResult,
    EvaluationCheck,
    EvaluationResult,
    FailureCategory,
    FailureReport,
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
        failure_reports = self._failure_reports(checks, result)
        return EvaluationResult(
            scenario_id=scenario.scenario_id,
            passed=all(check.passed for check in checks),
            checks=checks,
            failure_reports=failure_reports,
        )

    def _failure_reports(
        self, checks: list[EvaluationCheck], result: AgentResult
    ) -> list[FailureReport]:
        categories = {
            "execution_status": (
                FailureCategory.ENVIRONMENT_FAILURE,
                "inspect the run error and tool failure before changing the agent",
                ("tool.failed", "agent.completed"),
            ),
            "required_tools": (
                FailureCategory.TOOL_SELECTION_FAILURE,
                "review the agent tool-selection path and expected tool contract",
                ("tool.completed", "tool.failed"),
            ),
            "forbidden_tools": (
                FailureCategory.PERMISSION_FAILURE,
                "tighten the permission policy or remove the forbidden action path",
                ("permission.checked", "tool.completed", "tool.failed"),
            ),
            "max_steps": (
                FailureCategory.LOOP_BUDGET_FAILURE,
                "bound the agent loop and reduce repeated or unnecessary tool calls",
                ("tool.completed", "tool.failed"),
            ),
            "expected_terms": (
                FailureCategory.RETRIEVAL_FAILURE,
                "inspect retrieved files and evidence before changing the answer",
                ("tool.completed", "agent.completed"),
            ),
        }
        reports: list[FailureReport] = []
        for check in checks:
            if check.passed:
                continue
            category, likely_fix, event_types = categories[check.name]
            evidence = [
                event.event_id for event in result.trace if event.event_type in event_types
            ]
            if not evidence:
                evidence = [event.event_id for event in result.trace]
            reports.append(
                FailureReport(
                    category=category,
                    evidence_event_ids=evidence,
                    confidence=0.95,
                    likely_fix=likely_fix,
                )
            )
        return reports

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
