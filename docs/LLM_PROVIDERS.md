# Interoperable LLM Gateway

## Scope

The interviewer uses one provider-neutral gateway contract for Databricks and Azure AI Foundry. The local mock remains the default, so setup, tests, and voice-pipeline development never require a paid request.

The gateway normalizes:

- System, user, and assistant messages.
- Maximum output tokens and temperature.
- Optional strict JSON Schema output.
- Final text, token usage, and parsed structured data.
- Server-sent event text deltas.
- Timeouts, bounded retries, and secret-safe failures.

Optional sampler fields such as `temperature` are omitted by default because some reasoning-oriented models reject them. Callers may still set them explicitly for compatible deployments.

## Provider Matrix

| Backend | Wire format | Authentication | Endpoint construction |
| --- | --- | --- | --- |
| `databricks` | OpenAI-compatible Responses API | `Authorization: Bearer ...` | Appends `/ai-gateway/mlflow/v1/responses` unless a complete gateway or Responses URL is supplied |
| `azure_foundry` | Model inference Chat Completions API | `api-key: ...` | Appends `/models/chat/completions` and the configured `api-version` |
| `mock` | In-process deterministic adapter | None | No network |

Both remote adapters implement the existing `InterviewLanguageModel` behavior through `GatewayInterviewLLM`. The lower-level `HttpLLMGateway` also exposes normalized completion and streaming methods for the structured interview engine.

## Databricks Configuration

```powershell
$env:VOICE_LLM_BACKEND = 'databricks'
$env:DATABRICKS_HOST = 'https://your-workspace.example'
$env:DATABRICKS_TOKEN = '<read-from-your-secret-store>'
$env:DATABRICKS_MODEL = 'your-serving-model'
```

`DATABRICKS_HOST` may also be the full AI Gateway base ending in `/ai-gateway/mlflow/v1` or the full `/responses` URL.

## Azure AI Foundry Configuration

```powershell
$env:VOICE_LLM_BACKEND = 'azure_foundry'
$env:AZURE_FOUNDRY_ENDPOINT = 'https://your-resource.services.ai.azure.com/models'
$env:AZURE_FOUNDRY_API_KEY = '<read-from-your-secret-store>'
$env:AZURE_FOUNDRY_MODEL = 'your-deployment-name'
$env:AZURE_FOUNDRY_API_VERSION = '2024-05-01-preview'
```

The endpoint may be the resource root, `/models`, or a full `/chat/completions` URL. An existing `api-version` query parameter is preserved.

## Common Controls

| Variable | Default | Meaning |
| --- | --- | --- |
| `VOICE_LLM_TIMEOUT_SECONDS` | `30` | Per-request HTTP timeout |
| `VOICE_LLM_MAX_RETRIES` | `2` | Retries for timeouts, connection errors, rate limits, and transient server responses |
| `VOICE_LLM_STREAMING` | `false` | Consume provider SSE internally while preserving the current final-text pipeline contract |

Retries use bounded exponential backoff and honor numeric `Retry-After` values. A stream is retried only before its first text delta; retrying a partially emitted stream could duplicate content.

## Structured Output

`LLMRequest.response_schema` maps to the Responses API `text.format` shape and the Chat Completions `response_format.json_schema` shape. Returned text is parsed as JSON before it is exposed as `LLMResponse.json_data`. Malformed structured output fails explicitly instead of silently falling back to unvalidated text.

The conversation-engine checkpoint will use this capability for interview actions, state updates, rubric evidence, and final feedback.

## Secret Safety

- Provider credentials are read only from backend process environment variables.
- Secret fields are excluded from the `Settings` representation.
- HTTP clients ignore ambient proxy configuration.
- Errors include provider and status only, never response bodies or authorization headers.
- `/health` and `doctor` report configuration booleans, never credential values.
- Tests use `httpx.MockTransport` and make no external provider calls.

Never place credentials in `.env.example`, browser code, canvas payloads, prompts, logs, or Git history.

## Local Validation

```powershell
. .\scripts\env.ps1
uv run pytest tests\test_llm_gateway.py
```

The contract suite covers both payload formats, endpoint construction, authentication headers, final response parsing, SSE parsing, strict JSON Schema requests, retry behavior, provider selection, and secret-safe errors.
