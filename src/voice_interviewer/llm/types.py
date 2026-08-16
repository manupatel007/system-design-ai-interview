from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

MessageRole = Literal["system", "user", "assistant"]


class LLMApiStyle(StrEnum):
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class LLMJsonSchema:
    name: str
    schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: tuple[LLMMessage, ...]
    max_output_tokens: int = 160
    temperature: float | None = 0.2
    response_schema: LLMJsonSchema | None = None


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: LLMUsage
    json_data: Any | None = None


@dataclass(frozen=True, slots=True)
class LLMStreamChunk:
    text: str = ""
    done: bool = False


class LanguageModelGateway(Protocol):
    provider: str
    model: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]: ...
