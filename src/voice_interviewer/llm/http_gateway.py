from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

import httpx

from voice_interviewer.errors import LLMProviderError
from voice_interviewer.llm.types import (
    LLMApiStyle,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
)

RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
Sleeper = Callable[[float], Awaitable[None]]


class HttpLLMGateway:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        endpoint: str,
        api_style: LLMApiStyle,
        auth_headers: Mapping[str, str],
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_base_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("LLM timeout must be positive")
        if max_retries < 0:
            raise ValueError("LLM max retries cannot be negative")
        parsed_endpoint = httpx.URL(endpoint)
        if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.host:
            raise ValueError("LLM endpoint must be an absolute HTTP(S) URL")
        self.provider = provider
        self.model = model
        self.endpoint = str(parsed_endpoint)
        self.api_style = api_style
        self._headers = {"Content-Type": "application/json", **auth_headers}
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._transport = transport
        self._sleeper = sleeper

    async def complete(self, request: LLMRequest) -> LLMResponse:
        body = self._request_body(request, stream=False)
        for attempt in range(self._max_retries + 1):
            try:
                async with self._client() as client:
                    response = await client.post(self.endpoint, headers=self._headers, json=body)
            except httpx.RequestError as error:
                if attempt < self._max_retries:
                    await self._wait_before_retry(attempt, None)
                    continue
                raise LLMProviderError(
                    f"{self.provider} request failed before receiving a response"
                ) from error
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                await self._wait_before_retry(attempt, response)
                continue
            self._raise_for_status(response)
            return self._parse_response(request, response)
        raise AssertionError("unreachable retry loop")

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        body = self._request_body(request, stream=True)
        for attempt in range(self._max_retries + 1):
            emitted = False
            try:
                async with self._client() as client:
                    async with client.stream(
                        "POST", self.endpoint, headers=self._headers, json=body
                    ) as response:
                        if (
                            response.status_code in RETRYABLE_STATUS_CODES
                            and attempt < self._max_retries
                        ):
                            await response.aread()
                            await self._wait_before_retry(attempt, response)
                            continue
                        self._raise_for_status(response)
                        async for line in response.aiter_lines():
                            event = self._parse_sse_line(line)
                            if event is None:
                                continue
                            chunk = self._stream_chunk(event)
                            if chunk is None:
                                continue
                            if chunk.text:
                                emitted = True
                            yield chunk
                            if chunk.done:
                                return
                        yield LLMStreamChunk(done=True)
                        return
            except httpx.RequestError as error:
                if emitted or attempt >= self._max_retries:
                    raise LLMProviderError(
                        f"{self.provider} streaming request was interrupted"
                    ) from error
                await self._wait_before_retry(attempt, None)
        raise AssertionError("unreachable retry loop")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            trust_env=False,
        )

    def _request_body(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        messages = [
            {"role": message.role, "content": message.content} for message in request.messages
        ]
        if self.api_style is LLMApiStyle.RESPONSES:
            body: dict[str, Any] = {
                "model": self.model,
                "input": messages,
                "max_output_tokens": request.max_output_tokens,
                "stream": stream,
            }
            if request.response_schema:
                body["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": request.response_schema.name,
                        "schema": request.response_schema.schema,
                        "strict": request.response_schema.strict,
                    }
                }
        else:
            body = {
                "model": self.model,
                "messages": messages,
                "max_tokens": request.max_output_tokens,
                "stream": stream,
            }
            if request.response_schema:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.response_schema.name,
                        "schema": request.response_schema.schema,
                        "strict": request.response_schema.strict,
                    },
                }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        return body

    def _parse_response(self, request: LLMRequest, response: httpx.Response) -> LLMResponse:
        try:
            payload = response.json()
        except ValueError as error:
            raise LLMProviderError(f"{self.provider} returned invalid JSON") from error
        text = self.extract_text(payload, self.api_style).strip()
        if not text:
            raise LLMProviderError(f"{self.provider} returned no response text")
        json_data: Any | None = None
        if request.response_schema:
            try:
                json_data = json.loads(text)
            except json.JSONDecodeError as error:
                raise LLMProviderError(
                    f"{self.provider} returned invalid structured output"
                ) from error
        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            usage=self.extract_usage(payload),
            json_data=json_data,
        )

    @staticmethod
    def extract_text(payload: dict[str, Any], api_style: LLMApiStyle) -> str:
        if api_style is LLMApiStyle.RESPONSES:
            if isinstance(payload.get("output_text"), str):
                return payload["output_text"]
            parts: list[str] = []
            for item in payload.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"} and content.get("text"):
                        parts.append(str(content["text"]))
            return "".join(parts)
        choices = payload.get("choices", [])
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content", "")
        return HttpLLMGateway._content_text(content)

    @staticmethod
    def extract_usage(payload: dict[str, Any]) -> LLMUsage:
        usage = payload.get("usage", {})
        return LLMUsage(
            input_tokens=_optional_int(usage.get("input_tokens", usage.get("prompt_tokens"))),
            output_tokens=_optional_int(usage.get("output_tokens", usage.get("completion_tokens"))),
        )

    def _stream_chunk(self, payload: dict[str, Any]) -> LLMStreamChunk | None:
        if payload.get("_done"):
            return LLMStreamChunk(done=True)
        if self.api_style is LLMApiStyle.RESPONSES:
            event_type = payload.get("type")
            if event_type in {"response.completed", "response.done"}:
                return LLMStreamChunk(done=True)
            if event_type in {"error", "response.failed"}:
                raise LLMProviderError(f"{self.provider} reported a streaming failure")
            delta = payload.get("delta")
            if event_type in {"response.output_text.delta", "output_text.delta"} and isinstance(
                delta, str
            ):
                return LLMStreamChunk(text=delta)
            return None
        choices = payload.get("choices", [])
        if not choices:
            return None
        choice = choices[0]
        text = self._content_text(choice.get("delta", {}).get("content", ""))
        return LLMStreamChunk(text=text, done=bool(choice.get("finish_reason")))

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        return ""

    @staticmethod
    def _parse_sse_line(line: str) -> dict[str, Any] | None:
        if not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if not data:
            return None
        if data == "[DONE]":
            return {"_done": True}
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as error:
            raise LLMProviderError("Provider returned malformed SSE data") from error
        return payload if isinstance(payload, dict) else None

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_error:
            raise LLMProviderError(
                f"{self.provider} request failed with status {response.status_code}",
                status_code=response.status_code,
            )

    async def _wait_before_retry(self, attempt: int, response: httpx.Response | None) -> None:
        retry_after = _retry_after_seconds(response)
        delay = retry_after if retry_after is not None else self._retry_base_seconds * 2**attempt
        await self._sleeper(min(delay, 5.0))


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    raw_value = response.headers.get("Retry-After")
    if raw_value is None:
        return None
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return None


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None
