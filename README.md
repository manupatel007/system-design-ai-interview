# Local Voice Interviewer Scaffold

Runnable local-first voice pipeline for an AI system-design interviewer. The scaffold keeps speech recognition and voice activity detection local, uses mock LLM and TTS adapters by default, and exposes a browser/WebSocket path for testing turn-taking alongside canvas activity.

## Pipeline

```text
Browser microphone (16 kHz PCM)
  -> Silero VAD
  -> faster-whisper base.en
  -> canvas-aware turn gate
  -> mock or Databricks interviewer LLM
  -> mock or future local TTS
  -> browser audio playback
```

The mock mode requires no model downloads or API credentials. The production-oriented local mode uses the pinned Silero ONNX model and the `Systran/faster-whisper-base.en` checkpoint.

## Requirements

- Windows PowerShell
- [`uv`](https://docs.astral.sh/uv/)
- A modern CPU with approximately 2 GB free RAM for the base configuration
- Microphone access in the browser

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
5. Downloads a small pinned speech sample to `.cache\test-assets`.
6. Prints a sanitized readiness report.

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

For local Silero VAD and `base.en` transcription with mock Databricks/TTS:

```powershell
. .\scripts\env.ps1
uv run voice-interviewer serve
```

Open `http://127.0.0.1:8000`, connect, start the microphone, and draw on the canvas while speaking. The mock TTS emits an audible tone sequence to verify playback and interruption without pretending to be production speech.

## Validate Local STT

```powershell
. .\scripts\env.ps1
uv run python scripts/smoke_transcribe.py
```

The smoke test runs the local `base.en` adapter against the pinned JFK WAV sample. It makes no paid API calls.

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
| `VOICE_LLM_BACKEND` | `mock` | `mock` or `databricks` |
| `VOICE_TTS_BACKEND` | `mock` | Mock tone adapter until a local TTS is selected |
| `VOICE_VAD_MIN_SILENCE_MS` | `1200` | Patient speech endpointing for interviews |
| `VOICE_CANVAS_QUIET_MS` | `1500` | Canvas inactivity required before a response |

When `VOICE_LLM_BACKEND=databricks`, set `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and optionally `DATABRICKS_MODEL`. Never commit or paste the token into the browser. The backend is disabled by default and tests never call it.

## Current Boundaries

- Whisper partial transcripts are intentionally not fed to the LLM. Only finalized utterances trigger reasoning.
- `base.en` is English-only and must be evaluated on expected accents and technical vocabulary.
- Silero VAD determines speech boundaries; the separate turn gate decides whether the candidate has yielded the floor.
- The canvas is a signaling stub, not the final structured architecture editor.
- Mock TTS verifies the protocol and barge-in path but is not natural speech.
- Raw audio is held only for the active utterance and is not persisted.

See `docs/VOICE_PIPELINE.md`, `docs/EVENT_PROTOCOL.md`, and `docs/EVALUATION_PLAN.md` for implementation details and acceptance criteria.
