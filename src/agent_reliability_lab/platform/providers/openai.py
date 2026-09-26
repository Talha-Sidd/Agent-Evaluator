"""OpenAI Responses API adapter; SDK objects stay inside this provider boundary."""

import json
import os
from typing import Any, cast

from openai.types.responses import (
    EasyInputMessageParam,
    FunctionToolParam,
)

from agent_reliability_lab.domain.model_gateway import (
    ModelConfig,
    ModelMessage,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelToolRequest,
)

REPO_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "repo_search",
    "description": "Find repository files whose content matches the query.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    },
}


def _to_openai_input(messages: list[ModelMessage]) -> list[EasyInputMessageParam]:
    # Responses API input uses user/assistant messages here. Tool output is data,
    # so encode it as a labeled user message; it never becomes trusted instructions.
    result: list[EasyInputMessageParam] = []
    for message in messages:
        role = "assistant" if message.role == "assistant" else "user"
        content = message.content
        if message.role == "tool":
            content = "Untrusted tool result data (JSON):\n" + content
        result.append(cast(EasyInputMessageParam, {"role": role, "content": content}))
    return result


def _parse_response(response: Any) -> ModelResponse:
    usage = response.usage
    if usage is None:
        raise ValueError("provider response omitted usage")
    functions = [item for item in response.output if item.type == "function_call"]
    if len(functions) > 1:
        raise ValueError("provider returned multiple tool calls")
    if functions:
        function = functions[0]
        arguments = json.loads(function.arguments)
        if not isinstance(arguments, dict):
            raise ValueError("function arguments must be an object")
        return ModelResponse(
            tool=ModelToolRequest(name=function.name, arguments=arguments),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
    answer = response.output_text
    if not isinstance(answer, str) or not answer:
        raise ValueError("provider response omitted both text and a tool call")
    return ModelResponse(
        final_answer=answer,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )


class OpenAIProvider(ModelProvider):
    """Stateless, spawn-safe adapter; constructs the SDK client in the worker."""

    def complete(self, request: ModelRequest, config: ModelConfig) -> ModelResponse:
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is not configured")
        from openai import OpenAI

        client = OpenAI(max_retries=0)
        input_messages = _to_openai_input(request.messages)
        tools = [cast(FunctionToolParam, REPO_SEARCH_TOOL)]
        input_count = client.responses.input_tokens.count(
            model=config.model,
            instructions=config.system_prompt,
            input=input_messages,
            tools=tools,
        )
        if input_count.input_tokens > config.max_input_tokens:
            raise ValueError("model input exceeds configured token limit")
        # The SDK's generated create overload rejects its own EasyInputMessageParam
        # list alias; isolate that typing mismatch at this validated boundary.
        sdk_input: Any = input_messages
        response = client.responses.create(
            model=config.model,
            instructions=config.system_prompt,
            input=sdk_input,
            tools=tools,
            tool_choice="auto",
            max_output_tokens=config.max_output_tokens,
            store=False,
        )
        return _parse_response(response)
