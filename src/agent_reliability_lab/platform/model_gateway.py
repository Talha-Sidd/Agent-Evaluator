"""Supervised provider execution and parent-owned budget/accounting checks."""

import time
from dataclasses import dataclass

from agent_reliability_lab.domain.errors import ToolExecutionError
from agent_reliability_lab.domain.model_gateway import (
    ModelConfig,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from agent_reliability_lab.domain.models import ErrorCode, ModelCall
from agent_reliability_lab.platform.security import fingerprint
from agent_reliability_lab.platform.workers import (
    Connection,
    receive_json,
    send_json,
    start_worker,
    stop_worker,
)


def _provider_worker(
    connection: Connection, provider: ModelProvider, request: ModelRequest, config: ModelConfig
) -> None:
    try:
        response = provider.complete(request, config)
        response = ModelResponse.model_validate(response.model_dump())
        send_json(connection, {"response": response.model_dump(mode="json")})
    except Exception:  # noqa: BLE001 -- provider exceptions may contain secrets
        send_json(connection, {"error": ErrorCode.MODEL_ERROR})
    finally:
        connection.close()


@dataclass(frozen=True)
class FakeProvider:
    """Importable scripted provider indexed by the harness-owned call ordinal."""

    responses: tuple[ModelResponse, ...]

    def complete(self, request: ModelRequest, config: ModelConfig) -> ModelResponse:
        index = request.call_index
        if index >= len(self.responses):
            raise ValueError("fake response script exhausted")
        return self.responses[index].model_copy(deep=True)


class ModelGateway:
    def __init__(self, provider: ModelProvider, config: ModelConfig) -> None:
        self.provider = provider
        self.config = ModelConfig.model_validate(config.model_dump())

    def record(self, request: ModelRequest) -> ModelCall:
        config = self.config
        return ModelCall(
            provider=config.provider,
            model=config.model,
            prompt_version=config.prompt_version,
            request_sha256=fingerprint({
                "request": request.model_dump(), "system_prompt": config.system_prompt,
            }),
            input_usd_per_million=config.input_usd_per_million,
            output_usd_per_million=config.output_usd_per_million,
        )

    def complete(
        self, request: ModelRequest, call: ModelCall, prior: list[ModelCall], deadline: float
    ) -> ModelResponse:
        config = self.config
        request = ModelRequest.model_validate(request.model_dump())
        request.call_index = len(prior)
        call.request_sha256 = self.record(request).request_sha256
        if len(prior) >= config.max_calls:
            raise ToolExecutionError(ErrorCode.MODEL_CALL_LIMIT_EXCEEDED)
        # Reserve the worst permitted request before contacting the provider.
        used_tokens = sum((c.input_tokens or 0) + (c.output_tokens or 0) for c in prior)
        if used_tokens + config.max_input_tokens + config.max_output_tokens > config.token_budget:
            raise ToolExecutionError(ErrorCode.TOKEN_BUDGET_EXCEEDED)
        reserved_cost = (
            config.max_input_tokens * config.input_usd_per_million
            + config.max_output_tokens * config.output_usd_per_million
        ) / 1_000_000
        if sum(c.estimated_cost_usd or 0 for c in prior) + reserved_cost > config.cost_budget_usd:
            raise ToolExecutionError(ErrorCode.COST_BUDGET_EXCEEDED)
        if deadline <= time.monotonic():
            raise ToolExecutionError(ErrorCode.TIMEOUT)
        started = time.monotonic()
        try:
            process, connection = start_worker(_provider_worker, self.provider, request, config)
            call.executed = True
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not connection.poll(remaining):
                    raise ToolExecutionError(ErrorCode.TIMEOUT)
                message = receive_json(connection)
                if "error" in message:
                    raise ToolExecutionError(ErrorCode.MODEL_ERROR)
                response = ModelResponse.model_validate(message["response"])
                call.input_tokens = response.input_tokens
                call.output_tokens = response.output_tokens
                call.estimated_cost_usd = (
                    response.input_tokens * config.input_usd_per_million
                    + response.output_tokens * config.output_usd_per_million
                ) / 1_000_000
                call.response_sha256 = fingerprint(response.model_dump())
                if (
                    response.input_tokens > config.max_input_tokens
                    or response.output_tokens > config.max_output_tokens
                ):
                    raise ToolExecutionError(ErrorCode.MODEL_ERROR)
                call.success = True
                return response
            finally:
                stop_worker(process, connection)
        except ToolExecutionError:
            raise
        except Exception:  # noqa: BLE001 -- fail closed on malformed provider IPC
            raise ToolExecutionError(ErrorCode.MODEL_ERROR) from None
        finally:
            call.duration_ms = (time.monotonic() - started) * 1000
