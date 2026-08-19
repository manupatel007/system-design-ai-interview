# Local TTS Latency Findings

## Executive Conclusion

The four-to-five-second pause is real and is inside Kokoro inference, not audio transport.
For a representative 18-word interviewer turn that produces about 6.23 seconds of audio:

| Local path | First playable audio | Synthesis completes | Real-time factor |
| --- | ---: | ---: | ---: |
| Kokoro, ONNX Runtime CPU, full response | 13.81 s | 13.81 s | 2.22 |
| Kokoro, ONNX Runtime CPU, clause split | 5.36 s | 13.94 s | about 2.4 |
| Kokoro, native OpenVINO CPU, full response | 6.44 s | 6.44 s | 1.03 |
| Kokoro, native OpenVINO CPU, clause split | 2.50 s | 6.28 s | about 1.1 |
| Piper lessac-medium, sentence chunks | 0.18-0.25 s | 0.46-0.59 s | 0.08-0.11 |
| Cached PCM acknowledgement | effectively immediate | about 0.002 s delivery work | not applicable |

These values measure synthesis availability, not how long playback takes. Piper and Kokoro also
produce different waveforms and durations, so speed alone cannot decide the product choice.

The practical conclusion is:

- Tuning the current ONNX Runtime session cannot make uncached Kokoro speech sub-second.
- Native OpenVINO roughly halves Kokoro compute time and clause splitting can start it near 2.5
  seconds, while preserving the Kokoro model.
- Piper is the measured route to sub-second local speech and was selected for this research
  integration after listening to system-design interview samples.

Piper is now the default runtime backend. Kokoro remains selectable for comparison.

## Scope and Method

Measurements were taken on 19 August 2026 on:

- Windows 11 x64
- Intel Core i5-1135G7
- 8 logical CPUs
- Intel Iris Xe integrated graphics
- Kokoro-82M v1.0 INT8 with af_heart
- kokoro-onnx 0.5.0
- ONNX Runtime 1.28.0 for the application baseline
- OpenVINO 2026.3.0 for the native Intel experiment
- Piper 1.7.0 with en_US-lessac-medium

The representative text was:

    That gives us a useful scale assumption. Walk me through the main components and the end-to-end request flow.

CPU tables use three measured repetitions unless a row is explicitly described as exploratory.
Piper uses five repetitions. Results are point-in-time measurements, not portable latency
guarantees. Power state, background load, thermal state, model cache state, and text all matter.

The benchmark outputs are written under .runtime and intentionally ignored by Git:

- .runtime/tts-latency-benchmark-v2.json
- .runtime/tts-openvino-native-benchmark.json
- .runtime/tts-piper-benchmark.json
- .runtime/tts-onnx-profile-summary.json

## Integrated Delivery Path

    accepted structured interview plan
      -> assistant.text.final
      -> Piper synthesizes the first sentence
      -> assistant.audio.chunk with chunkIndex 0
      -> browser starts queued playback
      -> later sentences synthesize and queue sequentially
      -> assistant.response.completed after playback duration

The synchronous Piper iterator advances in worker threads, so each sentence becomes playable
without blocking the server event loop. The browser uses one Web Audio scheduling cursor to avoid
overlap and clears active and future sources on barge-in.

Piper is shared across sessions and guarded by one synthesis lock. A cancelled native sentence
inference still finishes before that engine is reused. The optional Kokoro backend retains its
complete-utterance delivery behavior.

## Baseline CPU Results

### ONNX Runtime Thread Scaling

| Session | Median wall | Range | RTF | Median effective CPU cores |
| --- | ---: | ---: | ---: | ---: |
| Default session | 13.81 s | 12.49-13.91 s | 2.22 | 2.84 |
| 1 intra-op thread, sequential | 13.31 s | 12.88-13.42 s | 2.14 | 0.97 |
| 2 intra-op threads, sequential | 12.91 s | 12.91-13.04 s | 2.07 | 1.65 |
| 4 intra-op threads, sequential | 13.81 s | 13.60-13.83 s | 2.22 | 2.82 |
| 8 intra-op threads, sequential | 14.43 s | 13.87-14.58 s | 2.32 | 5.07 |
| 4 intra-op threads, parallel | 12.84 s | 12.84-12.85 s | 2.06 | 2.92 |

Latency essentially saturates at two useful threads. Four-thread parallel execution was only about
0.5 percent faster than two-thread sequential execution while consuming substantially more CPU.
Eight threads were slower. More worker threads are therefore a throughput and contention risk, not
a meaningful latency fix.

### Response Shaping

| Change | Median synthesis | Generated audio | RTF | What it buys |
| --- | ---: | ---: | ---: | --- |
| Normal speed 1.0 | 13.81 s | 6.23 s | 2.22 | Baseline |
| Speed 1.25 | 11.89 s | 5.42 s | 2.19 | About 14 percent less waiting by speaking 13 percent less audio |
| First seven-word clause | 5.36 s | 2.18 s | 2.46 | Earlier first audio |
| Both clauses sequentially | 13.94 s | 5.80 s total | about 2.4 | No material compute saving |

Increasing speech speed does not make inference more efficient; the RTF is almost unchanged.
Application-level clause segmentation reduces perceived latency by about 61 percent but leaves
total synthesis work almost unchanged.

The dependency's create_stream method splits around its 510-phoneme model limit. The representative
turn has 114 phonemes, so it remains one batch and one late chunk. Normal interviewer turns need
application-level sentence or clause segmentation.

### Cold and Small-Call Costs

| Operation | Observed time |
| --- | ---: |
| ONNX model and voices load with warm OS cache | 2.49 s |
| Earlier cold model loads | about 7-10 s |
| First phonemizer setup in the repeated run | 0.72 s |
| Warm phonemization | 0.0003 s |
| First one-word Kokoro inference | 2.27 s |
| Base64 encoding of the representative PCM | about 0.002 s |

Prewarming removes model and phonemizer setup from the interview, but even a one-word uncached
Kokoro utterance takes more than two seconds on this CPU.

An offline optimized ORT model reduced a separate warm-cache load experiment from about 3.43 to
1.43 seconds. It did not materially change inference. Graph serialization is a startup
optimization, not a speech-start optimization.

## Operator-Level Bottleneck

The reproducible ONNX Runtime profile covers the final representative run at two threads:

| Operator | Node time | Share of node time | Calls |
| --- | ---: | ---: | ---: |
| ConvInteger | 8.01 s | 71.07 percent | 87 |
| Mul | 0.79 s | 7.05 percent | 441 |
| Add | 0.68 s | 6.00 percent | 410 |
| Sin | 0.39 s | 3.43 percent | 51 |
| STFT | 0.24 s | 2.16 percent | 1 |
| ConvTranspose | 0.17 s | 1.54 percent | 6 |

The slowest individual nodes are quantized convolutions in the decoder generator residual and
noise blocks. This is the hard compute bottleneck. Token preparation, warm phonemization, PCM
conversion, Base64 encoding, and WebSocket transport are too small to move the result materially.

## Native OpenVINO Experiment

Native OpenVINO avoids the incompatible ONNX Runtime OpenVINO provider experiment and directly
executes the same Kokoro ONNX graph through a small session adapter.

At two CPU inference threads:

| Measurement | Result |
| --- | ---: |
| Read and compile model | 12.73 s |
| Short warm-up utterance | 3.34 s |
| Full response median | 6.44 s |
| Full response range | 5.64-7.31 s |
| Full response RTF | 1.03 |
| First clause median | 2.50 s |
| Second clause median | 3.78 s |
| Both clauses total | 6.28 s |

Compared with the tuned ONNX Runtime path, native OpenVINO cuts full-response compute by about 50
percent and gets close to real time. It still does not stream samples from within a model call, so
full-response first audio remains late. Clause splitting is still required.

The 12-second compile cost must happen before readiness. A representative-length startup warm-up
is safer than warming only one short phrase because dynamic input lengths can show first-shape
variance.

This is an experimental benchmark, not yet a production adapter. Package versions, waveform
equivalence, lifecycle, cancellation, concurrency, and compiled-model caching need validation.

## Piper Comparison

The en_US-lessac-medium model is approximately 60.3 MiB on disk. Kokoro INT8 plus its voice pack is
approximately 115 MiB.

| Piper measurement | Result |
| --- | ---: |
| Model load | 2.57-5.17 s |
| One-word warm-up | 0.092-0.376 s |
| First sentence chunk median | 0.183-0.249 s |
| Complete two-sentence synthesis median | 0.462-0.586 s |
| Individual synthesis range | 0.441-0.771 s |
| Generated audio | about 5.7 s |
| RTF | 0.081-0.108 |

Piper emits one chunk per sentence and runs much faster than playback on this CPU. It is the clear
latency winner. The benchmark does not score naturalness, pronunciation, emotional range, or
interviewer presence. Those are product requirements, not safe assumptions from timing data.

Before choosing it, run a blind listening test over system-design vocabulary, numbers, acronyms,
interruptions, acknowledgements, and longer follow-ups.

## Accelerator Findings

- DirectML exposed the Iris Xe device but Kokoro inference failed at ConvTranspose with HRESULT
  80070057.
- Native OpenVINO GPU compilation failed because linear_onnx interpolation in this graph receives a
  rank-three tensor while the Intel GPU plugin supports ranks two, four, or five for that mode.
- The ONNX Runtime OpenVINO provider experiment had a wheel and OpenVINO runtime compatibility
  issue and silently fell back to CPU. The successful numbers above use native OpenVINO instead.
- No NVIDIA CUDA device is available on this machine.

An execution provider appearing in the provider list does not prove the full model is supported.
The graph must compile and complete representative inference without fallback.

## Hard Bottlenecks

1. Kokoro's decoder is convolution dominated. Quantized convolution alone consumes about 71
   percent of profiled node time.
2. The model returns a complete waveform per call. Ordinary turns are below the dependency's split
   threshold, so native streaming produces one late chunk.
3. Very short uncached Kokoro calls still have a multi-second floor on this CPU.
4. CPU latency scaling saturates around two useful threads; adding threads wastes CPU and can hurt
   multi-session throughput.
5. The current DirectML and Iris Xe OpenVINO GPU paths encounter unsupported graph operations.
6. One process-wide synthesis lock serializes sessions, and Python cancellation does not stop an
   already-running native inference.
7. Prewarming removes startup work but cannot remove the steady model compute floor.

These are the reasons prompt tweaks, Base64 optimization, faster WebSockets, and more CPU threads
cannot produce sub-second uncached Kokoro speech here.

## Integrated Strategy

### Default Research Path

Piper `en_US-lessac-medium` is integrated behind the common TTS adapter, preloaded during server
startup when ready, and streamed sentence by sentence through a sequential browser queue. This is
the only tested local path below one second on this machine.

The runtime is GPL-3.0-or-later and the Lessac model card points to a research-only dataset
license that excludes commercial speech products. The selected voice must not silently cross into
commercial deployment.

### If Kokoro voice quality is required

Prototype the native OpenVINO CPU adapter with two inference threads, a startup compile plus
representative warm-up, and application-level clause streaming. Expect roughly 2.5 seconds to an
uncached first clause, not sub-second speech.

### Improvements useful with either backend

1. Record LLM time, TTS queue wait, load, phonemization, inference, encoding, network send, and
   browser playback-start separately.
2. Pre-render a small set of action-compatible acknowledgements such as Understood or Please
   continue. Cached PCM delivery is effectively immediate.
3. Keep spoken turns to one acknowledgement and one focused question while retaining richer text
   on screen.
4. Add played-text reconciliation and measure audible gaps between streamed sentences.
5. Benchmark two simultaneous interviews. Single-session latency tuning must not multiply CPU
   demand beyond physical capacity.

Avoid mixing noticeably different voices within one interviewer session unless listening tests
show that a fast acknowledgement voice and a main response voice feel coherent.

## Reproducing the Benchmarks

Keep uv cache and all optional environments on the F-drive workspace:

    $env:UV_CACHE_DIR = "$PWD/.runtime/uv-cache"

Baseline Kokoro and operator profile:

    uv run python scripts/benchmark_tts_latency.py --thread-counts 1,2,4,8 --repetitions 3 --include-parallel
    uv run python scripts/profile_tts_onnx.py --threads 2 --runs 2

Optional native OpenVINO environment:

    uv venv .runtime/tts-openvino-venv --python 3.13
    uv pip install --python .runtime/tts-openvino-venv/Scripts/python.exe openvino kokoro-onnx
    & .runtime/tts-openvino-venv/Scripts/python.exe scripts/benchmark_tts_openvino.py --devices CPU --cpu-threads 2 --repetitions 3

Integrated Piper environment and voice:

    uv sync
    uv run python scripts/download_models.py --piper
    uv run python scripts/benchmark_tts_piper.py --repetitions 5

The benchmark-only OpenVINO environment remains isolated. Piper is part of the application lockfile.
