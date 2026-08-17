# Local TTS Latency Findings

## Summary

Kokoro speech currently starts late because the server synthesizes the complete response before
emitting any audio. On the current CPU-only development machine, warm Kokoro ONNX inference runs
at approximately 2.5 times the generated audio duration. Phonemization, trimming, PCM conversion,
Base64 encoding, and browser delivery are not the primary bottlenecks.

This is intentionally documented for a later optimization checkpoint. No latency workaround is
enabled by default yet.

## Current Delivery Path

```text
accepted structured interview plan
  -> assistant.text.final
  -> synthesize the complete utterance
  -> convert the complete waveform to PCM16
  -> Base64-encode one complete audio event
  -> assistant.audio.chunk
  -> browser playback
```

The text is visible before TTS begins, but the browser receives no playable samples until the
entire Kokoro call finishes. The pipeline then waits for the calculated playback duration before
emitting `assistant.response.completed`; that final sleep does not delay first audio.

Kokoro is shared across sessions and guarded by one synthesis lock. A cancelled native inference
continues until its worker thread finishes, so barge-in or concurrent sessions can add queue time
on top of inference latency.

## Measurement Environment

- Windows x64
- 8 logical CPUs
- `kokoro-onnx 0.5.0`
- `onnxruntime 1.28.0`
- `CPUExecutionProvider`; no GPU execution provider installed
- Kokoro-82M v1.0 INT8
- Voice `af_heart`, language `en-us`, speed `1.0` unless stated otherwise

These are point-in-time measurements on one development machine, not portable latency promises.

## Measured Latency

### Cold Costs

| Operation | Observed time |
| --- | ---: |
| Load ONNX model and voice pack | 7.1-9.9 seconds |
| First phonemizer setup | approximately 0.94 seconds |
| Warm phonemization | approximately 0.002 seconds |

The model and phonemizer should eventually be warmed before accepting an interview session. That
will remove cold-start delay but will not solve warm inference speed.

### Warm Synthesis by Response Length

| Response | Words | Synthesis | Generated audio | Real-time factor |
| --- | ---: | ---: | ---: | ---: |
| `Good.` | 1 | 2.30 s | 0.70 s | 3.27 |
| `Walk me through the main components.` | 6 | 4.30 s | 1.73 s | 2.49 |
| `That gives us a useful scale assumption.` | 7 | 5.41 s | 2.18 s | 2.49 |
| Typical acknowledgement plus question | 18 | 15.62 s | 6.23 s | 2.51 |
| Longer follow-up | 34 | 31.78 s | 12.57 s | 2.53 |

The reported four-to-five-second delay matches a short six- or seven-word clause on this CPU.
Longer natural interviewer responses can wait substantially longer because audio is batch
generated.

### Representative 18-Word Breakdown

| Stage | Time |
| --- | ---: |
| First-call phonemization | 0.9415 s |
| Kokoro ONNX inference | 15.4817 s |
| Silence trimming | 0.1424 s |
| Float-to-PCM16 conversion | 0.0021 s |
| Base64 encoding | 0.0061 s |

ONNX inference dominates. Optimizing Base64 transport or the JavaScript PCM conversion will not
materially improve time to first audio.

Increasing speech speed from `1.0` to `1.25` reduced the representative synthesis from 15.62 to
13.55 seconds. This is a modest improvement, not a complete solution.

## Options, in Recommended Order

### 1. Add Latency Telemetry

Record separate durations for:

- LLM planning
- TTS lock/queue wait
- TTS cold load
- phonemization
- ONNX inference
- audio conversion and encoding
- server send to browser playback

Expose aggregated metrics rather than transcript or audio content. This distinguishes remote LLM
latency from TTS latency and catches contention after concurrency is introduced.

### 2. Prewarm TTS

Load Kokoro and synthesize a short discarded phrase during application startup. Mark the server
ready only after warm-up succeeds, or expose separate process-ready and model-ready health states.

Expected benefit: removes the 7-10 second load and first-inference penalty from the first interview
response. It does not change the approximately 2.5 warm real-time factor.

### 3. Stream Deliberate Speech Segments

Change the TTS adapter contract from one `AudioOutput` to an asynchronous sequence of audio
segments. Split accepted interviewer speech into a short acknowledgement followed by one question,
synthesize the first segment immediately, and queue later segments in the browser.

The dependency's current `create_stream` batches around its 510-phoneme model limit. Normal
interviewer responses are shorter than that and therefore remain a single batch. Application-level
sentence or clause segmentation is required.

On this machine, segmentation could reduce an 18-word response from roughly 15.6 seconds to around
4.3-5.4 seconds before its first uncached clause. It will not provide sub-second uncached speech on
the current CPU.

The browser must schedule chunks sequentially rather than calling `source.start()` immediately for
every arrival, otherwise chunks may overlap or contain audible gaps.

### 4. Cache Safe Acknowledgements

Pre-render a bounded set of semantically neutral phrases such as `Understood.` and `Please
continue.` Play a compatible cached acknowledgement after the structured plan is accepted while
the question synthesizes.

This provides near-immediate perceived responsiveness without speaking unvalidated streamed JSON.
The phrase selection must match the accepted action; an enthusiastic cached acknowledgement should
not be played for an incorrect or off-topic answer.

### 5. Shorten Spoken Responses

Keep visual text detailed if needed, but constrain spoken output to one acknowledgement and one
short question. This improves inference approximately in proportion to generated audio length and
also produces a more natural interviewer turn.

Speech speed between `1.1` and `1.25` may be acceptable after voice evaluation, but it is only a
secondary lever.

### 6. Accelerate or Replace the Runtime

Benchmark, rather than assume, the following on target hardware:

- CUDA ONNX Runtime on an available NVIDIA GPU
- DirectML on Windows GPUs
- OpenVINO on supported Intel hardware
- A dedicated local TTS worker with an appropriate accelerator
- Piper or another CPU-oriented streaming TTS backend

Keeping Kokoro with accelerated inference preserves the current voice quality. A smaller
CPU-oriented backend is more likely to meet a strict low-cost latency target but may trade away
prosody and naturalness.

If uncached semantic speech must begin in under one or two seconds, the current CPU Kokoro path is
unlikely to meet the target through prompt shortening and chunking alone.

### 7. Consider Speculative Synthesis Later

The structured engine often knows the likely next phase question while the candidate is still
speaking. It could synthesize a template speculatively and discard it if the accepted plan differs.
This should follow telemetry, cancellation-safe streaming, and a bounded phrase/template policy;
otherwise it wastes CPU and increases lock contention.

## Non-Solutions

- Enabling gateway SSE alone: structured JSON is currently buffered and validated before state or
  speech is accepted.
- Base64 micro-optimization: measured encoding is only a few milliseconds.
- Raising TTS speed alone: the observed gain is modest.
- Calling the existing dependency stream method without application segmentation: ordinary short
  interview responses still form one batch.
- Adding more concurrent calls to the same shared session: this can increase CPU contention and
  queue time.

## Proposed Later Checkpoint

1. Add stage-level latency telemetry and regression thresholds.
2. Prewarm Kokoro during application lifespan startup.
3. Introduce an asynchronous TTS segment contract.
4. Split acknowledgement and question speech safely.
5. Add a sequential, interruptible browser playback queue.
6. Benchmark accelerated Kokoro and a Piper-class CPU backend.
7. Select the backend using time-to-first-audio, real-time factor, naturalness, and memory results.
