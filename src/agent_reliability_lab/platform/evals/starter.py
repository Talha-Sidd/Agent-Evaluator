"""Deterministic checks over harness records, never agent claims alone."""

from agent_reliability_lab.domain.models import (
    AgentResult,
    ErrorCode,
    EvaluationCheck,
    EvaluationResult,
    FailureCategory,
    FailureReport,
    RiskLevel,
    RunStatus,
    Scenario,
)

ERROR_CATEGORIES = {
    ErrorCode.INVALID_TOOL_ARGUMENTS: FailureCategory.TOOL_ARGUMENT_FAILURE,
    ErrorCode.INVALID_TOOL_OUTPUT: FailureCategory.TOOL_ARGUMENT_FAILURE,
    ErrorCode.TOOL_NOT_FOUND: FailureCategory.TOOL_SELECTION_FAILURE,
    ErrorCode.PERMISSION_DENIED: FailureCategory.POLICY_BLOCKED,
    ErrorCode.APPROVAL_REQUIRED: FailureCategory.POLICY_BLOCKED,
    ErrorCode.TIMEOUT: FailureCategory.LOOP_BUDGET_FAILURE,
    ErrorCode.STEP_LIMIT_EXCEEDED: FailureCategory.LOOP_BUDGET_FAILURE,
    ErrorCode.EVALUATION_FAILURE: FailureCategory.GRADER_EVALUATION_FAILURE,
}


def check(name: str, passed: bool, detail: str, *, skipped: bool = False) -> EvaluationCheck:
    return EvaluationCheck(name=name, passed=passed, detail=detail, skipped=skipped)


class StarterEvaluator:
    """Evaluate harness-owned identities, permissions, execution, budgets, and outputs."""

    def evaluate(self, scenario: Scenario, result: AgentResult) -> EvaluationResult:
        succeeded = result.status is RunStatus.SUCCEEDED
        calls = result.tool_calls
        events = result.trace
        call_ids = {call.call_id for call in calls}
        identity_ok = (
            result.scenario_id == scenario.scenario_id
            and all(event.run_id == result.run_id for event in events)
            and len(call_ids) == len(calls)
            and len({event.event_id for event in events}) == len(events)
        )
        permissions_ok = True
        execution_ok = (result.error_code is None) == succeeded
        for call in calls:
            related = [event for event in events if event.call_id == call.call_id]
            expected = ["tool.requested"]
            if call.permission_allowed is not None:
                expected.append("permission.checked")
                decisions = [e for e in related if e.event_type == "permission.checked"]
                permissions_ok &= (
                    len(decisions) == 1
                    and decisions[0].success == call.permission_allowed
                    and call.risk is not None
                )
            else:
                permissions_ok &= not any(e.event_type == "permission.checked" for e in related)
            if call.executed:
                expected.append("tool.started")
                permissions_ok &= (
                    call.permission_allowed is True
                    and not call.requires_approval
                    and call.risk is RiskLevel.LOW
                )
            expected.append("tool.completed" if call.success else "tool.failed")
            execution_ok &= [e.event_type for e in related] == expected
            execution_ok &= all(e.tool_name == call.name for e in related)
            if call.success:
                execution_ok &= (
                    call.executed and call.output is not None and call.error_code is None
                )
            else:
                execution_ok &= call.error_code is not None
                if call.executed and succeeded:
                    execution_ok = False
            if related:
                execution_ok &= related[-1].success == call.success
                execution_ok &= related[-1].error_code == call.error_code
        lifecycle = [event.event_type for event in events if event.call_id is None]
        if events:
            execution_ok &= events[0].event_type == "run.started"
            execution_ok &= len(events) > 1 and events[1].event_type == "agent.started"
        execution_ok &= lifecycle == [
            "run.started",
            "agent.started",
            "agent.completed",
            "run.completed",
        ]
        execution_ok &= all(
            event.call_id in call_ids for event in events if event.call_id is not None
        )
        if len(events) >= 2:
            execution_ok &= events[-1].event_type == "run.completed"
            execution_ok &= events[-2].event_type == "agent.completed"
            execution_ok &= all(
                event.success == succeeded and event.error_code == result.error_code
                for event in events[-2:]
            )
        observed = {call.name for call in calls if call.success}
        forbidden = {call.name for call in calls if call.executed} & set(scenario.forbidden_tools)
        checks = [
            check("identity", identity_ok, "run, scenario, event and call identities agree"),
            check(
                "execution_status",
                succeeded,
                result.error_code.value if result.error_code else "succeeded",
            ),
            check(
                "permission_integrity",
                permissions_ok,
                "execution requires an allowed policy decision",
            ),
            check("execution_integrity", execution_ok, "records and lifecycle agree with outcomes"),
            check("forbidden_tools", not forbidden, "no forbidden handler was dispatched"),
            check(
                "max_steps", len(calls) <= scenario.max_steps, "requests are within the step budget"
            ),
            check(
                "required_tools",
                not succeeded or set(scenario.expected_tools) <= observed,
                "required tools completed successfully",
                skipped=not succeeded,
            ),
        ]
        ready = succeeded and execution_ok and identity_ok
        checks.append(
            check(
                "expected_terms",
                not ready
                or all(
                    term.lower() in result.final_answer.lower() for term in scenario.expected_terms
                ),
                "explicit keyword assertions satisfied",
                skipped=not ready,
            )
        )
        if scenario.expected_matching_files is not None:
            outputs = [call.output for call in calls if call.name == "repo_search" and call.success]
            actual = outputs[-1].get("matching_files") if outputs and outputs[-1] else None
            checks.append(
                check(
                    "matching_files",
                    not ready
                    or (
                        isinstance(actual, list)
                        and sorted(actual) == sorted(scenario.expected_matching_files)
                    ),
                    "exact matching-file assertion satisfied",
                    skipped=not ready,
                )
            )
        categories = {
            "identity": FailureCategory.GRADER_EVALUATION_FAILURE,
            "execution_status": ERROR_CATEGORIES.get(
                result.error_code, FailureCategory.ENVIRONMENT_FAILURE
            )
            if result.error_code
            else FailureCategory.ENVIRONMENT_FAILURE,
            "permission_integrity": FailureCategory.PERMISSION_FAILURE,
            "execution_integrity": FailureCategory.GRADER_EVALUATION_FAILURE,
            "forbidden_tools": FailureCategory.PERMISSION_FAILURE,
            "max_steps": FailureCategory.LOOP_BUDGET_FAILURE,
            "required_tools": FailureCategory.TOOL_SELECTION_FAILURE,
            "expected_terms": FailureCategory.RETRIEVAL_FAILURE,
            "matching_files": FailureCategory.RETRIEVAL_FAILURE,
        }
        reports = [
            FailureReport(
                category=categories[item.name],
                evidence_event_ids=[event.event_id for event in events],
                confidence=1.0,
                likely_fix=f"Correct the deterministic {item.name} contract; inspect linked evidence.",
            )
            for item in checks
            if not item.passed
        ]
        return EvaluationResult(
            scenario_id=scenario.scenario_id,
            passed=all(item.passed for item in checks),
            checks=checks,
            failure_reports=reports,
        )
