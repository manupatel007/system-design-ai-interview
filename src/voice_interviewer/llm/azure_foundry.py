from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from voice_interviewer.errors import ConfigurationError
from voice_interviewer.llm.http_gateway import HttpLLMGateway
from voice_interviewer.llm.interviewer import GatewayInterviewLLM
from voice_interviewer.llm.types import LLMApiStyle


class AzureFoundryLLM(GatewayInterviewLLM):
    def __init__(
        self,
        *,
        endpoint: str | None,
        api_key: str | None,
        model: str,
        api_version: str = "2024-05-01-preview",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        use_streaming: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not endpoint or not api_key:
            raise ConfigurationError(
                "Azure Foundry backend requires AZURE_FOUNDRY_ENDPOINT and AZURE_FOUNDRY_API_KEY"
            )
        options = {}
        if sleeper is not None:
            options["sleeper"] = sleeper
        gateway = HttpLLMGateway(
            provider="azure_foundry",
            model=model,
            endpoint=self.chat_completions_url(endpoint, api_version),
            api_style=LLMApiStyle.CHAT_COMPLETIONS,
            auth_headers={"api-key": api_key},
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            **options,
        )
        super().__init__(gateway, use_streaming=use_streaming)

    @staticmethod
    def chat_completions_url(endpoint: str, api_version: str) -> str:
        parsed = urlsplit(endpoint)
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            target_path = path
        elif path.endswith("/models"):
            target_path = f"{path}/chat/completions"
        else:
            target_path = f"{path}/models/chat/completions"
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault("api-version", api_version)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, target_path, urlencode(query), parsed.fragment)
        )
