from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from voice_interviewer.errors import ConfigurationError
from voice_interviewer.llm.http_gateway import HttpLLMGateway
from voice_interviewer.llm.interviewer import GatewayInterviewLLM
from voice_interviewer.llm.types import LLMApiStyle
from voice_interviewer.models import InterviewContext


class DatabricksLLM(GatewayInterviewLLM):
    def __init__(
        self,
        *,
        host: str | None,
        token: str | None,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        use_streaming: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not host or not token:
            raise ConfigurationError(
                "Databricks backend requires DATABRICKS_HOST and DATABRICKS_TOKEN"
            )
        options = {}
        if sleeper is not None:
            options["sleeper"] = sleeper
        gateway = HttpLLMGateway(
            provider="databricks",
            model=model,
            endpoint=self.responses_url(host),
            api_style=LLMApiStyle.RESPONSES,
            auth_headers={"Authorization": f"Bearer {token}"},
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            **options,
        )
        super().__init__(gateway, use_streaming=use_streaming)

    @staticmethod
    def _build_prompt(context: InterviewContext) -> str:
        return GatewayInterviewLLM.build_context(context)

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        return HttpLLMGateway.extract_text(payload, LLMApiStyle.RESPONSES)

    @staticmethod
    def responses_url(host: str) -> str:
        base = host.rstrip("/")
        if base.endswith("/responses"):
            return base
        if base.endswith("/ai-gateway/mlflow/v1"):
            return f"{base}/responses"
        return f"{base}/ai-gateway/mlflow/v1/responses"
