from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from voice_interviewer.adapters import create_llm
from voice_interviewer.errors import ConfigurationError, LLMProviderError
from voice_interviewer.llm.azure_foundry import AzureFoundryLLM
from voice_interviewer.llm.databricks import DatabricksLLM
from voice_interviewer.llm.http_gateway import HttpLLMGateway
from voice_interviewer.llm.types import (
    LLMApiStyle,
    LLMJsonSchema,
    LLMMessage,
    LLMRequest,
)
from voice_interviewer.models import InterviewContext


async def no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_databricks_responses_contract() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [{"content": [{"type": "output_text", "text": "Why this cache?"}]}],
                "usage": {"input_tokens": 20, "output_tokens": 4},
            },
        )

    llm = DatabricksLLM(
        host="https://workspace.example",
        token="secret-databricks-token",
        model="interviewer-model",
        transport=httpx.MockTransport(handler),
    )
    answer = await llm.respond(
        InterviewContext(session_id="test", transcript="I would add a cache.")
    )

    assert answer == "Why this cache?"
    assert captured["url"] == ("https://workspace.example/ai-gateway/mlflow/v1/responses")
    assert captured["authorization"] == "Bearer secret-databricks-token"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "interviewer-model"
    assert "candidateTranscript" in body["input"][1]["content"]
    assert "temperature" not in body


@pytest.mark.asyncio
async def test_azure_foundry_chat_completions_contract() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("api-key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "What is your partition key?"}}],
                "usage": {"prompt_tokens": 18, "completion_tokens": 6},
            },
        )

    llm = AzureFoundryLLM(
        endpoint="https://foundry.example/models",
        api_key="secret-azure-key",
        model="deployment-name",
        transport=httpx.MockTransport(handler),
    )
    answer = await llm.respond(
        InterviewContext(session_id="test", transcript="I will shard the database.")
    )

    assert answer == "What is your partition key?"
    assert captured["url"] == (
        "https://foundry.example/models/chat/completions?api-version=2024-05-01-preview"
    )
    assert captured["api_key"] == "secret-azure-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "deployment-name"
    assert body["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_gateway_parses_structured_chat_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["name"] == "question"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"question":"Why?"}'}}]},
        )

    gateway = HttpLLMGateway(
        provider="test",
        model="model",
        endpoint="https://provider.example/chat/completions",
        api_style=LLMApiStyle.CHAT_COMPLETIONS,
        auth_headers={},
        transport=httpx.MockTransport(handler),
    )
    response = await gateway.complete(
        LLMRequest(
            messages=(LLMMessage(role="user", content="Ask one question"),),
            response_schema=LLMJsonSchema(
                name="question",
                schema={
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"],
                    "additionalProperties": False,
                },
            ),
        )
    )

    assert response.json_data == {"question": "Why?"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_style", "content"),
    [
        (
            LLMApiStyle.RESPONSES,
            b'data: {"type":"response.output_text.delta","delta":"How "}\n\n'
            b'data: {"type":"response.output_text.delta","delta":"many?"}\n\n'
            b'data: {"type":"response.completed"}\n\n',
        ),
        (
            LLMApiStyle.CHAT_COMPLETIONS,
            b'data: {"choices":[{"delta":{"content":"How "}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"many?"}}]}\n\n'
            b"data: [DONE]\n\n",
        ),
    ],
)
async def test_gateway_streams_sse(api_style: LLMApiStyle, content: bytes) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"Content-Type": "text/event-stream"})

    gateway = HttpLLMGateway(
        provider="test",
        model="model",
        endpoint="https://provider.example/generate",
        api_style=api_style,
        auth_headers={},
        transport=httpx.MockTransport(handler),
    )
    chunks = [chunk async for chunk in gateway.stream(_request())]

    assert "".join(chunk.text for chunk in chunks) == "How many?"
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_gateway_retries_rate_limit_without_leaking_secret() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"output_text": "What fails first?"})

    gateway = HttpLLMGateway(
        provider="test",
        model="model",
        endpoint="https://provider.example/responses",
        api_style=LLMApiStyle.RESPONSES,
        auth_headers={"Authorization": "Bearer never-print-this"},
        max_retries=1,
        transport=httpx.MockTransport(handler),
        sleeper=no_sleep,
    )
    response = await gateway.complete(_request())

    assert response.text == "What fails first?"
    assert attempts == 2


@pytest.mark.asyncio
async def test_gateway_error_is_status_only_and_secret_safe() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret-azure-key appeared upstream")

    gateway = HttpLLMGateway(
        provider="azure_foundry",
        model="model",
        endpoint="https://provider.example/chat/completions",
        api_style=LLMApiStyle.CHAT_COMPLETIONS,
        auth_headers={"api-key": "secret-azure-key"},
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMProviderError) as captured:
        await gateway.complete(_request())

    assert "status 401" in str(captured.value)
    assert "secret-azure-key" not in str(captured.value)


def test_provider_configuration_is_required() -> None:
    with pytest.raises(ConfigurationError):
        DatabricksLLM(host=None, token=None, model="model")
    with pytest.raises(ConfigurationError):
        AzureFoundryLLM(endpoint=None, api_key=None, model="model")


def test_llm_factory_selects_each_remote_provider(mock_settings) -> None:
    databricks = create_llm(
        replace(
            mock_settings,
            llm_backend="databricks",
            databricks_host="https://workspace.example",
            databricks_token="databricks-secret",
        )
    )
    azure = create_llm(
        replace(
            mock_settings,
            llm_backend="azure_foundry",
            azure_foundry_endpoint="https://foundry.example/models",
            azure_foundry_api_key="azure-secret",
        )
    )

    assert isinstance(databricks, DatabricksLLM)
    assert isinstance(azure, AzureFoundryLLM)


def test_settings_repr_redacts_provider_secrets(mock_settings) -> None:
    settings = replace(
        mock_settings,
        databricks_token="databricks-secret",
        azure_foundry_api_key="azure-secret",
    )

    assert "databricks-secret" not in repr(settings)
    assert "azure-secret" not in repr(settings)


def _request() -> LLMRequest:
    return LLMRequest(messages=(LLMMessage(role="user", content="Ask a question"),))
