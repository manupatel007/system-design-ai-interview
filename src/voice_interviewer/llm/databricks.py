from __future__ import annotations

from typing import Any

import httpx

from voice_interviewer.errors import ConfigurationError, VoicePipelineError
from voice_interviewer.models import InterviewContext


class DatabricksLLM:
    def __init__(
        self,
        *,
        host: str | None,
        token: str | None,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not host or not token:
            raise ConfigurationError(
                "Databricks backend requires DATABRICKS_HOST and DATABRICKS_TOKEN"
            )
        self._host = host.rstrip("/")
        self._token = token
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def respond(self, context: InterviewContext) -> str:
        prompt = self._build_prompt(context)
        url = self._responses_url()
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "model": self._model,
                    "input": [
                        {
                            "role": "system",
                            "content": (
                                "You are a system-design interviewer. Ask exactly one concise "
                                "question. Do not teach or reveal a solution."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_output_tokens": 100,
                },
            )
        if response.is_error:
            raise VoicePipelineError(
                f"Databricks request failed with status {response.status_code}"
            )
        text = self._extract_text(response.json())
        if not text:
            raise VoicePipelineError("Databricks returned no response text")
        return text.strip()

    def _responses_url(self) -> str:
        if self._host.endswith("/ai-gateway/mlflow/v1"):
            return f"{self._host}/responses"
        return f"{self._host}/ai-gateway/mlflow/v1/responses"

    @staticmethod
    def _build_prompt(context: InterviewContext) -> str:
        lines = [f"Candidate said: {context.transcript}"]
        if context.problem:
            lines.append(f"Interview problem: {context.problem}")
        if context.recent_diagram_delta:
            lines.append(f"Recent diagram change: {context.recent_diagram_delta}")
        if context.selected_object_ids:
            lines.append(f"Selected diagram objects: {', '.join(context.selected_object_ids)}")
        return "\n".join(lines)

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    return str(content["text"])
        return ""
