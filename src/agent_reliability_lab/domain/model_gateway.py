"""Provider-neutral model requests, usage, and harness configuration."""

from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class ModelMessage(Contract):
    role: Literal["user", "assistant", "tool"]
    content: str = Field(max_length=131072)


class ModelRequest(Contract):
    messages: list[ModelMessage] = Field(min_length=1, max_length=100)
    call_index: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if sum(len(message.content.encode()) for message in self.messages) > 131072:
            raise ValueError("model context exceeds 128 KiB")
        return self


class ModelToolRequest(Contract):
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]


class ModelResponse(Contract):
    final_answer: str | None = Field(default=None, max_length=65536)
    tool: ModelToolRequest | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def one_action(self) -> Self:
        if (self.final_answer is None) == (self.tool is None):
            raise ValueError("response must contain exactly one final answer or tool request")
        return self


class ModelConfig(Contract):
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1, max_length=16384)
    input_usd_per_million: float = Field(ge=0, le=10000, allow_inf_nan=False)
    output_usd_per_million: float = Field(ge=0, le=10000, allow_inf_nan=False)
    max_calls: int = Field(default=8, ge=1, le=100)
    max_input_tokens: int = Field(default=4096, ge=1, le=131072)
    max_output_tokens: int = Field(default=512, ge=1, le=16384)
    token_budget: int = Field(default=40000, ge=1, le=10000000)
    cost_budget_usd: float = Field(default=1.0, ge=0, le=1000, allow_inf_nan=False)


class ModelProvider(Protocol):
    """Trusted provider adapter; enforce input/output caps before making a live call."""

    def complete(self, request: ModelRequest, config: ModelConfig) -> ModelResponse: ...
