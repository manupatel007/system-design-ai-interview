# Local AI System Design Interviewer

Runnable local-first AI system-design interview workspace. Speech recognition, voice activity detection, and speech synthesis run locally; the interviewer planner remains mocked by default. A per-session conversation engine tracks the active question, phases, assumptions, decisions, evidence, rubric coverage, and final feedback while Excalidraw supplies validated diagram semantics.

## Pipeline

```text
Browser microphone (16 kHz PCM)
  -> Silero VAD
  -> faster-whisper base.en
  + structured Excalidraw snapshot
  -> canvas-aware turn gate
  -> stateful interview engine and evidence policy
  -> mock, Databricks, or Azure Foundry structured planner
  -> Kokoro-82M INT8 local TTS
  -> browser audio playback
```

The normal mode uses pinned Silero ONNX, `Systran/faster-whisper-base.en`, and Kokoro-82M v1.0 INT8 artifacts. `--mock` remains available for dependency-free protocol tests. No API credentials are required unless a remote LLM provider is selected.

## Requirements

- Windows PowerShell
- [`uv`](https://docs.astral.sh/uv/)
- A modern CPU with approximately 2 GB free RAM for the base configuration
- Microphone access in the browser
- Node.js 22+ and pnpm only when rebuilding the checked-in canvas bundle

Python dependencies, uv caches, Hugging Face caches, temporary downloads, model weights, and the virtual environment are all redirected beneath this project on the `F:` drive by `scripts/env.ps1`.

## Bootstrap

```powershell
.\scripts\bootstrap.ps1
```

This command:

1. Creates `.venv` in the project.
2. Installs dependencies with uv using `.cache\uv`.
3. Downloads Silero VAD to `.models\silero-vad`.
4. Downloads faster-whisper `base.en` to `.models\faster-whisper-base.en`.
5. Downloads Kokoro INT8 and its voice pack to `.models\kokoro`.
6. Downloads a small pinned speech sample to `.cache\test-assets`.
7. Prints a sanitized readiness report.

To install dependencies without model weights:

```powershell
.\scripts\bootstrap.ps1 -SkipModels
```

## Run

For an immediate end-to-end mock demonstration:

```powershell
. .\scripts\env.ps1
uv run voice-interviewer serve --mock
```

For local Silero VAD, `base.en` transcription, Kokoro speech, and the mock interviewer LLM:

```powershell
. .\scripts\env.ps1
uv run voice-interviewer serve
```

Open `http://127.0.0.1:8000` and connect. The interviewer opens the requirements phase automatically. Start the microphone, answer naturally, and draw on the Excalidraw canvas while speaking. The right panel shows the current phase, active question, covered topics, evidence and rubric coverage, exact diagram snapshot, and final feedback. Use **Finish interview** after your last explanation.

## Rebuild the Canvas UI

Runtime users do not need Node or internet access because the production bundle is checked in. After changing `frontend/`, rebuild and test it with:

```powershell
.\scripts\build_frontend.ps1
```

The pnpm store and cache remain beneath `.cache` on the `F:` workspace.

## Validate Local STT

```powershell
. .\scripts\env.ps1
uv run python scripts/smoke_transcribe.py
```

The smoke test runs the local `base.en` adapter against the pinned JFK WAV sample. It makes no paid API calls.

## Validate Local TTS

```powershell
. .\scripts\env.ps1
uv run python scripts/smoke_tts.py
```

This creates `.runtime\kokoro-smoke.wav` with real local speech. The first run includes ONNX and phonemizer warm-up; later responses reuse the loaded engine.

With the normal server running, exercise one complete real voice turn with:

```powershell
uv run python scripts/smoke_voice_turn.py
```

## Tests and Lint

```powershell
. .\scripts\env.ps1
uv run pytest
uv run ruff check .
```

## Configuration

Copy `.env.example` values into your process environment as needed. The server does not automatically read `.env`, preventing an accidental secret load.

| Variable | Default | Purpose |
| --- | --- | --- |
| `VOICE_STT_BACKEND` | `faster-whisper` | `faster-whisper` or `mock` |
| `VOICE_STT_MODEL` | `base.en` | Local Whisper model name |
| `VOICE_VAD_BACKEND` | `silero` | `silero` or development-only `energy` |
| `VOICE_LLM_BACKEND` | `mock` | `mock`, `databricks`, or `azure_foundry` |
| `VOICE_LLM_TIMEOUT_SECONDS` | `30` | Remote provider request timeout |
| `VOICE_LLM_MAX_RETRIES` | `2` | Bounded transient-failure retries |
| `VOICE_LLM_STREAMING` | `false` | Consume provider SSE through the common gateway |
| `VOICE_TTS_BACKEND` | `kokoro` | `kokoro` or `mock` |
| `VOICE_TTS_VOICE` | `af_heart` | Voice key from the Kokoro v1.0 voice pack |
| `VOICE_TTS_LANGUAGE` | `en-us` | Phonemizer language, normally `en-us` or `en-gb` |
| `VOICE_TTS_SPEED` | `1.0` | Speech speed from `0.5` to `2.0` |
| `VOICE_VAD_MIN_SILENCE_MS` | `1200` | Patient speech endpointing for interviews |
| `VOICE_CANVAS_QUIET_MS` | `1500` | Canvas inactivity required before a response |

Remote providers are disabled by default. See `docs/LLM_PROVIDERS.md` for Databricks and Azure AI Foundry endpoint, credential, retry, streaming, and structured-output configuration. Never commit credentials or paste them into the browser; provider contract tests use mock HTTP transports only.

## Current Boundaries

- Whisper partial transcripts are intentionally not fed to the LLM. Only finalized utterances trigger reasoning.
- `base.en` is English-only and must be evaluated on expected accents and technical vocabulary.
- Silero VAD determines speech boundaries; the separate turn gate decides whether the candidate has yielded the floor.
- Diagram roles are deterministic label heuristics unless an element supplies an explicit `customData.systemDesignRole`.
- Visual style and exact geometry remain in session state but are intentionally omitted from provider prompts.
- Live rubric levels represent evidence coverage, not a final hiring score; diagram shapes alone cannot upgrade them.
- Interview state is in memory only and is discarded when the WebSocket session closes.
- Provider plans require strict structured-output support; malformed plans fail without mutating state.
- Kokoro currently synthesizes a full response before sending one PCM chunk; clause streaming remains future work.
- Raw audio is held only for the active utterance and is not persisted.

See `docs/VOICE_PIPELINE.md`, `docs/STRUCTURED_CANVAS.md`, `docs/INTERVIEW_ENGINE.md`, `docs/LLM_PROVIDERS.md`, `docs/EVENT_PROTOCOL.md`, and `docs/EVALUATION_PLAN.md` for implementation details and acceptance criteria.
