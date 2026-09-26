"""Versioned, sanitized deterministic replay with full execution comparisons."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from agent_reliability_lab.agents.repopilot.demo import RepoPilotDemo
from agent_reliability_lab.domain.models import (
    AgentResult,
    EvaluationResult,
    ReplayCase,
    ReplayResult,
    Scenario,
)
from agent_reliability_lab.domain.protocols import AgentAdapter
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.security import require_safe_replay, sanitize


def normalize_execution(result: AgentResult, evaluation: EvaluationResult) -> dict[str, Any]:
    call_ids = {call.call_id: index for index, call in enumerate(result.tool_calls)}
    approval_ids = {
        value: index
        for index, value in enumerate(
            dict.fromkeys(
                event.approval_id for event in result.trace if event.approval_id is not None
            )
        )
    }
    calls = []
    for call in result.tool_calls:
        value = call.model_dump(mode="json")
        for key in ("call_id", "request_duration_ms", "worker_startup_ms"):
            value.pop(key)
        calls.append(value)
    events = []
    for event in result.trace:
        value = event.model_dump(mode="json")
        for key in ("event_id", "timestamp", "run_id"):
            value.pop(key)
        value["call_id"] = call_ids.get(event.call_id) if event.call_id is not None else None
        value["approval_id"] = approval_ids.get(event.approval_id) if event.approval_id else None
        events.append(value)
    return {
        "calls": calls,
        "events": events,
        "error_code": result.error_code,
        "checks": [item.model_dump(mode="json") for item in evaluation.checks],
        "failure_categories": [report.category.value for report in evaluation.failure_reports],
    }


class ReplayRunner:
    """Freeze safe baselines and compare normalized evidence from later runs."""

    def __init__(
        self, agent: AgentAdapter | None = None, runner: ScenarioRunner | None = None
    ) -> None:
        self._runner = runner or ScenarioRunner()
        self._agent = agent or RepoPilotDemo()
        self._evaluator = StarterEvaluator()

    def freeze(
        self,
        scenario: Scenario,
        result: AgentResult,
        evaluation: EvaluationResult,
        case_id: str,
    ) -> ReplayCase:
        require_safe_replay(scenario)
        if (
            result.scenario_id != scenario.scenario_id
            or evaluation.scenario_id != scenario.scenario_id
            or any(event.run_id != result.run_id for event in result.trace)
        ):
            raise ValueError("replay inputs must belong to the same run and scenario")
        evidence = normalize_execution(result, evaluation)
        if sanitize(evidence) != evidence or sanitize(result.final_answer) != result.final_answer:
            raise ValueError("replay evidence must be sanitized before export")
        return ReplayCase(
            schema_version=2,
            case_id=case_id,
            baseline_run_id=result.run_id,
            scenario=scenario.model_copy(deep=True),
            expected_status=result.status,
            expected_final_answer=result.final_answer,
            expected_tool_names=[call.name for call in result.tool_calls],
            expected_trace_event_types=[event.event_type for event in result.trace],
            expected_evaluation_passed=evaluation.passed,
            expected_execution=evidence,
        )

    def create_case(self, scenario: Scenario, case_id: str) -> ReplayCase:
        require_safe_replay(scenario)
        result = self._runner.run(self._agent, scenario)
        evaluation = self._evaluator.evaluate(scenario, result)
        return self.freeze(scenario, result, evaluation, case_id)

    def save_case(self, case: ReplayCase, path: Path, *, overwrite: bool = False) -> None:
        require_safe_replay(case.scenario)
        data = case.model_dump(mode="json")
        scenario_data = data.pop("scenario")
        if sanitize(data) != data:
            raise ValueError("replay evidence contains sensitive text")
        data["scenario"] = scenario_data
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, indent=2, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            if overwrite:
                os.replace(temporary, path)
            else:
                # An atomic no-clobber publish; existing artifacts remain untouched.
                os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load_case(self, path: Path) -> ReplayCase:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("replay artifact exceeds 4 MiB")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != 2:
            raise ValueError("unsupported replay schema; recreate and review a version 2 baseline")
        case = ReplayCase.model_validate(value)
        require_safe_replay(case.scenario)
        evidence = case.model_dump(mode="json")
        evidence.pop("scenario")
        if sanitize(evidence) != evidence:
            raise ValueError("replay evidence contains sensitive text")
        return case

    def replay(self, case: ReplayCase) -> ReplayResult:
        require_safe_replay(case.scenario)
        result = self._runner.run(self._agent, case.scenario)
        evaluation = self._evaluator.evaluate(case.scenario, result)
        differences: list[str] = []
        comparisons = [
            ("status", case.expected_status, result.status),
            ("final_answer", case.expected_final_answer, result.final_answer),
            ("tool_names", case.expected_tool_names, [call.name for call in result.tool_calls]),
            (
                "trace_event_types",
                case.expected_trace_event_types,
                [event.event_type for event in result.trace],
            ),
            ("evaluation_passed", case.expected_evaluation_passed, evaluation.passed),
        ]
        actual = normalize_execution(result, evaluation)
        for key in sorted(set(case.expected_execution) | set(actual)):
            comparisons.append(
                (f"execution.{key}", case.expected_execution.get(key), actual.get(key))
            )
        for name, expected, actual_value in comparisons:
            if expected != actual_value:
                # Do not echo arbitrary loaded artifact data into logs.
                differences.append(f"{name}: baseline and replay differ")
        return ReplayResult(
            case_id=case.case_id,
            replay_run_id=result.run_id,
            passed=not differences,
            differences=differences,
            evaluation=evaluation,
        )
