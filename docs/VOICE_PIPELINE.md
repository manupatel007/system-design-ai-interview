# Voice Pipeline Architecture

## Objective

Provide a local-first, observable voice loop for a system-design interview while keeping diagram awareness and interview policy outside the speech models.

The current scaffold validates this boundary:

```text
Browser audio
  -> audio normalization
  -> speech detection
  -> final transcription
  -> canvas-aware turn gate
  -> interviewer reasoning
  -> speech generation
  -> interruptible playback
```

## Component Diagram

```mermaid
flowchart LR
    MIC[Browser microphone] -->|PCM16 16 kHz| WS[WebSocket session]
    CANVAS[Excalidraw scene] --> REDUCER[Semantic diagram reducer]
    REDUCER -->|canvas.snapshot| WS
    WS --> FRAMES[512-sample frame buffer]
    FRAMES --> VAD[Silero ONNX VAD]
    VAD --> SEGMENT[Utterance segmenter]
    SEGMENT --> QUEUE[Transcription queue]
    QUEUE --> STT[faster-whisper base.en]
    STT --> GATE[Canvas-aware turn gate]
    WS --> GATE
    GATE --> LLM[Mock, Databricks, or Azure Foundry LLM]
    LLM --> TTS[Piper, Kokoro, or mock TTS]
    TTS -->|PCM16 audio event| WS
    WS --> PLAYBACK[Browser playback]
```

## Chosen Baseline

### Speech To Text

- Model: `base.en`
- Runtime: `faster-whisper` with CTranslate2
- Device: CPU
- Compute type: INT8
- Language: English only
- Invocation: one final decode per VAD-delimited utterance

When the pinned local artifacts are ready, the server loads the model once during application startup and retains it for the life of the process. The implementation passes NumPy audio directly to faster-whisper, avoiding a system FFmpeg dependency. Startup preload makes an unsafe memory state fail before an interview rather than during the first answer.

Partial Whisper decodes are intentionally absent from the decision loop. Re-decoding short rolling windows can create unstable or duplicated text. A future UI-only partial transcript layer may be added without allowing unstable text to trigger the interviewer.

### Voice Activity Detection

- Model: Silero VAD ONNX
- Frame size: 512 samples
- Sample rate: 16 kHz
- Frame duration: 32 ms
- Speech threshold: 0.5
- Negative threshold: 0.35
- Minimum speech: 192 ms
- Minimum silence: 1,200 ms
- Prefix padding: 256 ms

The ONNX wrapper preserves Silero's recurrent state and 64-sample context between frames. The downloaded artifact is pinned and checksum-verified by `scripts/download_models.py`.

The energy-based VAD exists only for dependency-free mock demonstrations and tests. It is not a production fallback.

### Language Model

The default `MockInterviewLLM` now exercises deterministic phase progression, question threading, evidence updates, and feedback without making network calls. Remote providers share a normalized gateway that supports messages, bounded output, strict JSON Schema output, final responses, SSE deltas, timeout handling, and bounded transient retries.

- Databricks uses its OpenAI-compatible Responses endpoint and bearer authentication.
- Azure AI Foundry uses model-inference Chat Completions and `api-key` authentication.
- Candidate transcript and a compact validated diagram snapshot are serialized as explicitly untrusted JSON evidence.
- A per-session engine adds the current phase, active question, assumptions, decisions, recent evidence, rubric coverage, and six recent turns.
- Provider output is a strict plan; the local reducer controls phase adjacency and state mutation.
- Diagram-only evidence cannot upgrade rubric coverage.
- Direct diagram-visibility and repeat-question repairs bypass the provider.
- Provider response bodies and authorization values are excluded from errors.
- Streams are retried only before their first emitted text delta.
- The current voice pipeline still waits for final interviewer text before batch TTS.

No remote request is made unless its `VOICE_LLM_BACKEND` value and required credential variables are explicitly configured. See `docs/INTERVIEW_ENGINE.md` and `docs/LLM_PROVIDERS.md` for the state, policy, and provider contracts.

### Text To Speech

- Default model: Piper `en_US-lessac-medium` ONNX
- Runtime: `piper-tts 1.7` with ONNX Runtime CPU execution
- Output: mono signed PCM16 at 22.05 kHz
- Delivery: one audio chunk per sentence
- Model footprint: approximately 60.3 MiB
- Alternate backend: Kokoro-82M v1.0 INT8 with `af_heart` at 24 kHz

The Piper model and configuration are revision- and checksum-pinned by `scripts/download_models.py`. `PiperTTS` retains one engine for the process, serializes synthesis, and maps the common speed control to Piper length scale. When artifacts are ready, the server loads the engine during application startup rather than delaying the first interview turn.

Piper's synchronous sentence iterator is advanced in worker threads. Each completed sentence is emitted immediately as `assistant.audio.chunk`; the browser schedules chunks against one Web Audio cursor so they do not overlap. Response completion accounts for playback already elapsed while later sentences were synthesized. Barge-in cancels delivery and clears both active and future browser sources.

`piper-tts 1.7` is GPL-3.0-or-later. The pinned [Lessac model card](https://huggingface.co/rhasspy/piper-voices/blob/f5a6e9094787fd865d65cb024472f977f9c542b5/en/en_US/lessac/medium/MODEL_CARD) points to a [research-only dataset license](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html) that expressly excludes commercial speech products. This research repository accepts that constraint; commercial use requires a separately approved runtime and voice.

Kokoro remains selectable with `VOICE_TTS_BACKEND=kokoro`. It retains its full-response adapter and measured CPU latency limitations. `ToneMockTTS` remains available under `--mock` for deterministic protocol tests. See `docs/TTS_LATENCY_FINDINGS.md` for the backend benchmarks.

## Turn Ownership

Speech endpointing and conversational turn completion are separate decisions.

The turn gate responds only when all applicable conditions are satisfied:

```text
final transcript exists
AND candidate is not currently speaking
AND canvas has been quiet for the configured interval
AND any explicit "let me draw" hold has expired
```

If speech restarts before the response begins, pending transcript fragments are retained and combined with the continuation. If the candidate starts speaking while the assistant is generating or playing audio, the response task is cancelled and an `assistant.interrupted` event tells the browser to stop playback.

After `session.configure`, the interviewer schedules a short introduction and first requirements question. Finishing waits for queued STT, drains the last transcript without the normal quiet delay, and generates structured feedback.

The current explicit drawing hold is a deterministic phrase matcher. A production version should use an intent classifier and release the hold when the promised canvas action completes rather than relying only on a timeout.

## Audio Capture

The browser requests:

- Echo cancellation.
- Noise suppression.
- Automatic gain control.
- One microphone channel.

An AudioWorklet resamples the browser's native capture rate to 16 kHz and sends signed 16-bit little-endian PCM frames. The backend re-chunks arbitrary message boundaries into the 512-sample frames required by Silero.

Production hardening should add:

- Audio-device change handling.
- Capture-level telemetry without retaining raw audio.
- A visible microphone permission state.
- A headset recommendation when echo cancellation is unreliable.
- Optional local noise suppression before VAD.

## Technical Vocabulary

The client supplies a glossary during session configuration. Diagram labels and inferred roles, with selected components first, are combined with that glossary into bounded faster-whisper `hotwords`. Opaque Excalidraw IDs are never used as vocabulary.

An earlier implementation used the natural-language initial prompt `System design interview. Expected technical terms: ...` for every utterance. A 350 ms speech fragment reproduced a prompt echo as the transcript `System design interview.` The adapter now uses the dedicated hotwords option, rejects segments over the standard compression-ratio limit, rejects low-log-probability or high-no-speech decodes, and drops incomplete connector words from sub-800 ms fragments. If no segment survives, the browser receives `candidate.transcript.rejected` and invites the candidate to retry instead of advancing the interview.

Good glossary entries are unusual, high-value terms:

```text
Kafka
Cassandra
PostgreSQL
gRPC
consistent hashing
p99 latency
QPS
idempotency
```

Avoid large lists of common words. Store the raw transcript separately from any later normalization so scoring remains auditable.

## Concurrency Model

- One WebSocket session owns its VAD recurrent state, segmenter, turn gate, and event sequence.
- The same session owns its mutable interview phase, question thread, evidence ledger, and rubric coverage.
- A per-session queue prevents audio reception from blocking during transcription.
- The STT adapter and loaded model are shared across sessions; inference is serialized by a lock.
- Canceled STT load/inference jobs are drained before their lock is released, preventing orphan native work after reconnects.
- The TTS adapter and loaded model are shared, with synthesis serialized by a lock.
- Response tasks are independently cancellable.
- WebSocket sends are serialized by an asynchronous lock.

Before multi-session deployment, benchmark CTranslate2 worker and CPU-thread settings. Do not multiply CPU threads by worker count beyond available physical cores.

## Storage and Privacy

- Raw audio remains in memory only for the active utterance.
- The scaffold does not record audio.
- Model weights and caches remain inside `.models` and `.cache` on `F:`.
- `.env`, caches, model weights, and runtime data are Git-ignored.
- Interview state remains in memory and is discarded when the WebSocket closes.
- Databricks and Azure Foundry credentials never reach browser JavaScript.
- The server does not automatically load `.env` files.

If transcript persistence is added, define consent, retention, encryption, deletion, and access-control policies before enabling it.

## Failure Behavior

| Failure | Current behavior | Production follow-up |
| --- | --- | --- |
| Silero model missing | WebSocket closes with `session_start_failed` | Surface guided download action |
| Piper files missing | Emits `response_failed` on first response | Run `scripts/download_models.py --piper` |
| Kokoro files missing | Emits `response_failed` when the alternate backend is selected | Run `scripts/download_models.py --kokoro` |
| STT MKL allocation failure | Emits actionable physical/commit headroom in `transcription_failed`; startup preload catches load failures earlier | Free commit, increase the Windows page file, and avoid duplicate native workers |
| Other STT inference failure | Emits `transcription_failed` | Retry once, then offer text input |
| Empty or unreliable transcript | Emits `candidate.transcript.rejected`; no interviewer response | Track rejection reason and input-level telemetry |
| Invalid plan or LLM failure | Emits `response_failed` before applying state | Provider fallback and retry |
| TTS failure | Preserves accepted state and text, then emits `response_failed` | Continue in text-only mode |
| Invalid JSON control event | Emits `invalid_json` | Add schema version negotiation |
| Invalid diagram snapshot | Emits `invalid_diagram` and retains prior state | Report client/schema mismatch |
| Browser disconnect | Cancels tasks and clears VAD state | Resume session from durable event log |

## Latency Budget

Initial targets for the target development machine:

| Stage | Target |
| --- | ---: |
| VAD processing per 32 ms frame | under 2 ms |
| Speech endpoint wait | 1,200 ms baseline, tunable |
| `base.en` final decode | under 600 ms p95 for a typical utterance |
| Canvas gate after final edit | 1,500 ms |
| Live LLM first token | under 800 ms p95 |
| Piper first sentence audio | under 300 ms p95 |
| Warm Piper synthesis | under 0.15 real-time factor |
| End of candidate turn to first audio | under 2 seconds p95 |

The VAD silence and canvas quiet periods overlap where possible. They should not be blindly summed in product latency calculations. Piper sentence streaming now supplies the low-latency TTS path; the end-to-end target still includes LLM planning and network scheduling.

## Windows Memory Headroom

CTranslate2 CPU allocations consume Windows commit, whose ceiling is physical RAM plus the page
file. The observed `mkl_malloc` incident occurred with only about 1.1 GB of remaining commit.
Cancellation previously allowed an executor thread to outlive its caller and overlap a new native
load or inference; adapter-level shielding and serialization now prevent that multiplier.

See `docs/STT_MEMORY_FINDINGS.md` for measured counters, the reproduction, and remediation steps.

## Next Implementation Steps

1. Add technical-term pronunciation overrides and played-text reconciliation for Piper chunks.
2. Add problem-specific rubric templates, time budgets, and configurable interview levels.
3. Add an explicit system-design component palette that writes semantic roles into Excalidraw `customData`.
4. Persist opt-in replayable session events for recovery and offline evaluation.
5. Add speculative LLM generation after a high-confidence eager endpoint, with cancellation.
6. Add provider fallbacks and circuit breakers.
7. Test conversation quality on low-end Windows hardware and expected candidate accents.
