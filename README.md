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
  -> Piper en_US-lessac-medium local TTS
  -> browser audio playback
```

The normal mode uses pinned Silero ONNX, `Systran/faster-whisper-base.en`, and Piper `en_US-lessac-medium` artifacts. Ready STT and TTS models load once during server startup and are shared across sessions. Piper emits sentence chunks that the browser queues for continuous playback. Kokoro remains available as an alternate backend, and `--mock` remains available for dependency-free protocol tests. No API credentials are required unless a remote LLM provider is selected.

> **Research-only voice:** [`piper-tts 1.7`](https://pypi.org/project/piper-tts/) is GPL-3.0-or-later. The pinned [Lessac model card](https://huggingface.co/rhasspy/piper-voices/blob/f5a6e9094787fd865d65cb024472f977f9c542b5/en/en_US/lessac/medium/MODEL_CARD) links to a [dataset license](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html) limited to research use that excludes commercial speech products. This repository intentionally uses it only for research. Select a separately approved runtime and voice before commercial deployment or redistribution.

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
5. Downloads the pinned Piper Lessac voice to `.models\piper`.
6. Downloads Kokoro INT8 and its voice pack as an alternate backend.
7. Downloads a small pinned speech sample to `.cache\test-assets`.
8. Prints a sanitized readiness report.

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

For local Silero VAD, `base.en` transcription, Piper speech, and the mock interviewer LLM:

```powershell
. .\scripts\env.ps1
uv run voice-interviewer serve
```

Open `http://127.0.0.1:8000` and join. The interviewer opens the requirements phase automatically. The meeting-style workspace keeps candidate and interviewer cards at the top, a scrollable conversation transcript on the left, and the Excalidraw architecture canvas as the primary surface. Interview setup remains available from the compact header menu, and final feedback appears beneath the transcript. Use **Finish interview** after your last explanation.

### Ask the AI What To Draw

Canvas proposals are model-driven and additive: the interviewer can suggest missing components,
labelled relationships, or a complete reference architecture without overwriting candidate work.

1. Draw and optionally select one or more components.
2. Say **?What should I draw here??** for a bounded, selection-scoped suggestion, or **?Show me a complete reference architecture?** for a reference layout.
3. Review the purple ghost objects and the explanation in the **AI canvas** panel.
4. Choose **Keep suggestion / Keep reference** or **Reject**. Kept AI objects remain editable.

Proposed objects carry `aiPreview` metadata and remain outside the semantic snapshot until the
candidate chooses **Keep**. Kept objects enter a separate `assistantLayer`, so later help can build
on earlier AI suggestions while candidate-authored nodes and edges remain the only diagram objects
eligible for evidence. The reducer validates IDs, limits size, and only permits proposals when the
candidate explicitly asks for help. Grounded feedback remains separate: numbered purple outlines
identify exact existing nodes or edges when the interviewer explains a diagram issue.

### Guided Takeover

Use Guided Takeover when you want the interviewer to take the floor and teach through the canvas
one reversible step at a time:

1. Reach a design question and optionally select the area you want extended.
2. Click **Walk me through** beside the canvas controls, or say **"Walk me through this design."**
3. The interviewer explains and automatically applies one bounded purple AI step. The panel shows
   the current step, objective, suggested questions, and **Scoring paused**.
4. Choose **Continue**, **Why?**, **Alternative**, a suggested-question chip, or **Take back**.
5. After the last step, explain the request path and trade-offs in your own words to resume the
   original interview question.

The default walkthrough covers entry/routing, the core request path, state and fast reads, then
asynchronous work and operations. One explicit takeover authorization permits its later steps to
apply automatically; the user does not need to approve every canvas mutation. **Undo AI** removes
an applied step. Every generated component remains in `assistantLayer`, is available to the next
walkthrough step, and is excluded from candidate evidence and rubric coverage.

### Ask for Scoped Help

Choose a **Practice support** policy in **Interview setup** before joining:

- **Strict** always returns a Socratic nudge.
- **Adaptive** returns a nudge, then a concept, then a bounded example when help is repeated.
- **Guided** starts with a concept and moves to a bounded example.

Ask naturally with phrases such as "I need a hint", "Can you give me more help?", or "Show
me an example." If canvas objects are selected, help is scoped to those objects and receives a
matching purple focus outline. Otherwise it stays scoped to the active question. A transcript
badge identifies each hint, concept, or worked example.

Assistance does not close the question, advance the phase, increment the phase escape counter, or
create candidate evidence. Selecting a different canvas area starts a fresh help sequence.

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

This creates `.runtime\tts-smoke.wav` with the configured real local TTS backend. A ready Piper model is loaded during server startup and reused across sessions.

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
| `VOICE_STT_DEVICE` | `cpu` | CTranslate2 device |
| `VOICE_STT_COMPUTE_TYPE` | `int8` | Low-memory CPU compute type |
| `VOICE_STT_CPU_THREADS` | `2` | Serialized STT worker threads; higher values increase scratch memory |
| `VOICE_VAD_BACKEND` | `silero` | `silero` or development-only `energy` |
| `VOICE_LLM_BACKEND` | `mock` | `mock`, `databricks`, or `azure_foundry` |
| `VOICE_LLM_TIMEOUT_SECONDS` | `30` | Remote provider request timeout |
| `VOICE_LLM_MAX_RETRIES` | `2` | Bounded transient-failure retries |
| `VOICE_LLM_STREAMING` | `false` | Consume provider SSE through the common gateway |
| `VOICE_TTS_BACKEND` | `piper` | `piper`, `kokoro`, or `mock` |
| `VOICE_PIPER_MODEL_PATH` | `.models/piper/en_US-lessac-medium.onnx` | Piper ONNX voice path inside the workspace |
| `VOICE_PIPER_CONFIG_PATH` | `.models/piper/en_US-lessac-medium.onnx.json` | Matching Piper voice configuration |
| `VOICE_TTS_VOICE` | `af_heart` | Kokoro-only voice key |
| `VOICE_TTS_LANGUAGE` | `en-us` | Kokoro-only phonemizer language |
| `VOICE_TTS_SPEED` | `1.0` | Backend-neutral speech speed from `0.5` to `2.0` |
| `VOICE_VAD_MIN_SPEECH_MS` | `192` | Sustained speech required before opening an utterance |
| `VOICE_VAD_MIN_SILENCE_MS` | `1200` | Patient speech endpointing for interviews |
| `VOICE_CANVAS_QUIET_MS` | `1500` | Canvas inactivity required before a response |

Remote providers are disabled by default. See `docs/LLM_PROVIDERS.md` for Databricks and Azure AI Foundry endpoint, credential, retry, streaming, and structured-output configuration. Never commit credentials or paste them into the browser; provider contract tests use mock HTTP transports only.

## Current Boundaries

- Whisper partial transcripts are intentionally not fed to the LLM. Only finalized utterances trigger reasoning.
- `base.en` is English-only and must be evaluated on expected accents and technical vocabulary.
- On Windows, `mkl_malloc` means RAM/page-file commit exhaustion. STT work is serialized and cancellation-drained, but the host still needs several GB of safe commit headroom.
- Silero VAD determines speech boundaries; the separate turn gate decides whether the candidate has yielded the floor.
- Diagram roles are deterministic label heuristics unless an element supplies an explicit `customData.systemDesignRole`.
- Visual style and exact geometry remain in session state but are intentionally omitted from provider prompts.
- Live rubric levels represent evidence coverage, not a final hiring score; diagram shapes alone cannot upgrade them.
- Interview state is in memory only and is discarded when the WebSocket session closes.
- Provider plans require strict structured-output support; malformed plans fail without mutating state.
- Guided Takeover currently uses a four-step generic blueprint; **Alternative** explains a branch but does not redraw or fork canvas history.
- Piper emits one PCM chunk per sentence; the browser schedules chunks sequentially and barge-in clears queued playback.
- Kokoro remains a full-response compatibility backend and does not provide low-latency sentence streaming.
- Raw audio is held only for the active utterance and is not persisted.

See `docs/VOICE_PIPELINE.md`, `docs/STT_MEMORY_FINDINGS.md`, `docs/TTS_LATENCY_FINDINGS.md`, `docs/STRUCTURED_CANVAS.md`, `docs/INTERVIEW_ENGINE.md`, `docs/LLM_PROVIDERS.md`, `docs/EVENT_PROTOCOL.md`, and `docs/EVALUATION_PLAN.md` for implementation details and acceptance criteria.
