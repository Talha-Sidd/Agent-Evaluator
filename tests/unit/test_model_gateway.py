"""Real parent/worker boundaries with scripted providers; no network calls."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_runtime_controls import registry_with_marker

from agent_reliability_lab.agents.repopilot.model import (
    REPOPILOT_PROMPT_VERSION,
    REPOPILOT_SYSTEM_PROMPT,
    RepoPilotModel,
)
from agent_reliability_lab.domain.model_gateway import (
    ModelConfig,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolRequest,
)
from agent_reliability_lab.domain.models import (
    AgentResult,
    ErrorCode,
    RiskLevel,
    RunStatus,
    Scenario,
)
from agent_reliability_lab.platform.evals.starter import StarterEvaluator
from agent_reliability_lab.platform.evals.suite import EvaluationSuite
from agent_reliability_lab.platform.model_gateway import FakeProvider, ModelGateway
from agent_reliability_lab.platform.replay.runner import normalize_execution
from agent_reliability_lab.platform.runner.runner import ScenarioRunner


def config(**overrides: object) -> ModelConfig:
    values = {
        "provider": "fake", "model": "scripted-v1", "prompt_version": REPOPILOT_PROMPT_VERSION,
        "system_prompt": REPOPILOT_SYSTEM_PROMPT, "input_usd_per_million": 1.0,
        "output_usd_per_million": 2.0,
    }
    return ModelConfig.model_validate(values | overrides)


def scenario(**overrides: object) -> Scenario:
    values = {
        "scenario_id": "model-search", "task": "authentication", "expected_behavior": "find auth.py",
        "expected_tools": ["repo_search"], "expected_matching_files": ["auth.py"],
        "repository_files": {"auth.py": "authentication", "other.py": "other"},
        "replay_safe": True,
    }
    return Scenario.model_validate(values | overrides)


def tool(name: str = "repo_search", **arguments: object) -> ModelResponse:
    return ModelResponse(
        tool=ModelToolRequest(name=name, arguments=arguments), input_tokens=100, output_tokens=10
    )


def gateway(responses: tuple[ModelResponse, ...], **overrides: object) -> ModelGateway:
    return ModelGateway(FakeProvider(responses), config(**overrides))


def test_model_tool_answer_and_parent_evidence() -> None:
    case = scenario()
    result = ScenarioRunner(gateway=gateway((
        tool(query="authentication", repository_files={"forged.py": "authentication"}),
        ModelResponse(final_answer="auth.py", input_tokens=120, output_tokens=20),
    ))).run(RepoPilotModel(), case)
    assert result.status is RunStatus.SUCCEEDED
    assert result.tool_calls[0].output == {"matching_files": ["auth.py"]}
    assert StarterEvaluator().evaluate(case, result).passed
    assert len(result.model_calls) == 2
    first = result.model_calls[0]
    assert first.input_tokens == 100 and first.output_tokens == 10
    assert first.estimated_cost_usd == pytest.approx(0.00012)
    assert first.provider == "fake" and first.prompt_version == REPOPILOT_PROMPT_VERSION
    assert first.duration_ms > 0 and first.executed and first.success
    assert "authentication" not in first.model_dump_json()
    restored = AgentResult.model_validate_json(result.model_dump_json())
    assert restored == result
    normalized = normalize_execution(result, StarterEvaluator().evaluate(case, result))
    assert "duration_ms" not in normalized["model_calls"][0]


@pytest.mark.parametrize("arguments,code", [
    ({}, ErrorCode.INVALID_TOOL_ARGUMENTS),
    ({"query": 42}, ErrorCode.INVALID_TOOL_ARGUMENTS),
    ({"query": "authentication", "extra": "bad"}, ErrorCode.INVALID_TOOL_ARGUMENTS),
])
def test_model_arguments_still_use_registry(arguments: dict[str, object], code: ErrorCode) -> None:
    result = ScenarioRunner(gateway=gateway((tool(**arguments),))).run(RepoPilotModel(), scenario())
    assert result.error_code is code
    assert not result.tool_calls[0].executed
    assert result.model_calls[0].success


@pytest.mark.parametrize("overrides,code", [
    ({"max_calls": 1}, ErrorCode.MODEL_CALL_LIMIT_EXCEEDED),
    ({"token_budget": 1}, ErrorCode.TOKEN_BUDGET_EXCEEDED),
    ({"cost_budget_usd": 0.0}, ErrorCode.COST_BUDGET_EXCEEDED),
])
def test_budget_rejected_before_provider_dispatch(overrides: dict[str, object], code: ErrorCode) -> None:
    result = ScenarioRunner(gateway=gateway((tool(query="authentication"),), **overrides)).run(
        RepoPilotModel(), scenario()
    )
    assert result.error_code is code
    assert not result.model_calls[-1].executed
    assert result.model_calls[-1].input_tokens is None
    assert result.model_calls[-1].error_code is code


def test_usage_contract_violation_is_recorded_and_fails() -> None:
    result = ScenarioRunner(gateway=gateway((
        ModelResponse(final_answer="done", input_tokens=5000, output_tokens=1),
    ))).run(RepoPilotModel(), scenario())
    assert result.error_code is ErrorCode.MODEL_ERROR
    assert result.model_calls[0].input_tokens == 5000
    assert not result.model_calls[0].success


def test_provider_failure_is_safe_and_preserves_prior_usage() -> None:
    result = ScenarioRunner(gateway=gateway((tool(query="authentication"),))).run(
        RepoPilotModel(), scenario()
    )
    assert result.error_code is ErrorCode.MODEL_ERROR
    assert len(result.model_calls) == 2
    assert result.model_calls[0].estimated_cost_usd is not None
    assert result.model_calls[1].estimated_cost_usd is None
    assert "exhausted" not in result.model_dump_json()


def test_missing_gateway_fails_closed() -> None:
    assert ScenarioRunner().run(RepoPilotModel(), scenario()).error_code is ErrorCode.MODEL_NOT_CONFIGURED


def test_permission_denial_does_not_execute_model_requested_action(tmp_path) -> None:
    marker = tmp_path / "marker"
    runner = ScenarioRunner(
        registry_with_marker(RiskLevel.HIGH),
        gateway=gateway((tool(name="sentinel", path=str(marker)),)),
    )
    result = runner.run(RepoPilotModel(), scenario())
    assert result.error_code is ErrorCode.APPROVAL_REQUIRED
    assert not marker.exists() and not result.tool_calls[0].executed


@dataclass
class SlowProvider:
    marker: str

    def complete(self, request: ModelRequest, config: ModelConfig) -> ModelResponse:
        from pathlib import Path

        time.sleep(5)
        Path(self.marker).write_text("late")
        return ModelResponse(final_answer="late", input_tokens=1, output_tokens=1)


def test_provider_deadline_terminates_worker(tmp_path) -> None:
    marker = tmp_path / "late"
    selected = ModelGateway(SlowProvider(str(marker)), config())
    request = ModelRequest(messages=[ModelMessage(role="user", content="task")])
    call = selected.record(request)
    from agent_reliability_lab.domain.errors import ToolExecutionError

    with pytest.raises(ToolExecutionError) as caught:
        selected.complete(request, call, [], time.monotonic() + 1.5)
    assert caught.value.code is ErrorCode.TIMEOUT
    assert call.executed and not marker.exists()


def test_strict_response_schema() -> None:
    with pytest.raises(ValidationError):
        ModelResponse.model_validate({"final_answer": "a", "input_tokens": "1", "output_tokens": 1})
    with pytest.raises(ValidationError):
        ModelResponse(input_tokens=1, output_tokens=1)


@pytest.mark.parametrize("overrides,code", [
    ({"token_budget": 4658}, ErrorCode.TOKEN_BUDGET_EXCEEDED),
    ({"cost_budget_usd": 0.00515}, ErrorCode.COST_BUDGET_EXCEEDED),
])
def test_budget_includes_prior_model_usage(overrides: dict[str, object], code: ErrorCode) -> None:
    result = ScenarioRunner(gateway=gateway((tool(query="authentication"),), **overrides)).run(
        RepoPilotModel(), scenario()
    )
    assert result.model_calls[0].success
    assert result.error_code is code and not result.model_calls[-1].executed


def test_tool_step_limit_still_applies_to_model_loop() -> None:
    result = ScenarioRunner(gateway=gateway((
        tool(query="authentication"), tool(query="authentication"),
    ))).run(RepoPilotModel(), scenario(max_steps=1))
    assert result.error_code is ErrorCode.STEP_LIMIT_EXCEEDED
    assert result.tool_calls[0].executed and not result.tool_calls[1].executed


@dataclass
class SearchProvider:
    """Fake using only agent-visible inputs, never evaluator expectations."""

    def complete(self, request: ModelRequest, config: ModelConfig) -> ModelResponse:
        if request.messages[-1].role == "user":
            return tool(query=request.messages[-1].content)
        matches = json.loads(request.messages[-1].content)["matching_files"]
        return ModelResponse(
            final_answer=f"RepoPilot found {len(matches)} relevant file(s): "
            + (", ".join(matches) if matches else "none"),
            input_tokens=100, output_tokens=20,
        )


def test_fake_model_evaluates_same_golden_cases() -> None:
    suite = EvaluationSuite(
        agent=RepoPilotModel(), runner=ScenarioRunner(gateway=ModelGateway(SearchProvider(), config()))
    )
    cases = suite.load_jsonl(Path("evals/datasets/repopilot_smoke.jsonl"))
    scorecard = suite.run(cases, "fake-model-baseline")
    assert scorecard.passed_cases == scorecard.total_cases == 10
    assert all(len(case.result.model_calls) == 2 for case in scorecard.cases)


def test_maximum_length_search_output_fits_context() -> None:
    files = {f"{i:03d}" + "x" * 509: "authentication" for i in range(128)}
    case = scenario(repository_files=files, expected_matching_files=list(files))
    result = ScenarioRunner(gateway=gateway((
        tool(query="authentication"),
        ModelResponse(final_answer="done", input_tokens=100, output_tokens=10),
    ))).run(RepoPilotModel(), case)
    assert result.status is RunStatus.SUCCEEDED and len(result.model_calls) == 2


def test_evaluator_rejects_corrupted_model_evidence() -> None:
    case = scenario()
    result = ScenarioRunner(gateway=ModelGateway(SearchProvider(), config())).run(RepoPilotModel(), case)
    result.model_calls[0].input_tokens = None
    evaluation = StarterEvaluator().evaluate(case, result)
    assert not next(check for check in evaluation.checks if check.name == "execution_integrity").passed


@dataclass
class MalformedProvider:
    def complete(self, request: ModelRequest, config: ModelConfig) -> ModelResponse:
        return ModelResponse.model_construct(final_answer="bad", input_tokens=-1, output_tokens=1)


def test_malformed_provider_response_fails_closed() -> None:
    result = ScenarioRunner(gateway=ModelGateway(MalformedProvider(), config())).run(
        RepoPilotModel(), scenario()
    )
    assert result.error_code is ErrorCode.MODEL_ERROR
    assert result.model_calls[0].executed and result.model_calls[0].input_tokens is None


def test_fake_script_ordinal_survives_context_trimming() -> None:
    files = {f"{i:03d}" + "x" * 509: "authentication" for i in range(128)}
    result = ScenarioRunner(gateway=gateway((
        tool(query="authentication"), tool(query="authentication"),
        ModelResponse(final_answer="done", input_tokens=100, output_tokens=10),
    ))).run(RepoPilotModel(), scenario(repository_files=files, expected_matching_files=list(files)))
    assert result.status is RunStatus.SUCCEEDED
    assert result.final_answer == "done" and len(result.model_calls) == 3
