# STT Memory Allocation Findings

## Conclusion

`mkl_malloc: failed to allocate memory` is a Windows commit-exhaustion error from the native
CTranslate2/MKL CPU runtime. It is not a Whisper decoding-quality problem, a corrupt `base.en`
model, or an `F:`-drive storage problem.

The failure was reproduced on 2026-08-20 while constructing `WhisperModel`, before any audio was
decoded. It can also occur during a later transcription because CTranslate2 allocates temporary
inference buffers after the model is already resident.

## Measured Failure State

| Counter | Measured value |
| --- | ---: |
| Physical RAM | 7,915 MB |
| Available physical memory | 324-1,083 MB during diagnostics |
| Windows commit limit | 32,491 MB |
| Committed memory | 31,401-32,452 MB during diagnostics |
| Remaining commit headroom | 39-1,101 MB |
| CTranslate2 | 4.8.1 |
| faster-whisper | 1.2.1 |
| Model/runtime | `base.en`, CPU, INT8 |

Windows commit is the allocation ceiling backed by RAM plus the page file. A process can fail
`malloc` even when the model file exists and the drive has free space if the remaining commit
headroom is below a native allocation peak.

## Host-Level Evidence

The final snapshot showed 32,452 MB committed against the 32,491 MB limit with no interviewer or
Uvicorn process running. The remaining Python helper processes together used about 34 MB private
memory. Grouped private memory showed roughly 2.3 GB in VS Code and 0.9 GB in Edge, while all
process private bytes totaled about 9.7 GB. The much larger global commit figure therefore also
contains system, kernel, driver, and shared-section commitments that Task Manager's per-process
memory column does not fully explain.

Close/restart the visible heavy applications first. If the global **Committed** value does not fall
by several GB, restart Windows before running `base.en`; this clears stale system/shared
commitments that restarting only the Python server cannot reclaim.

## Application Amplifiers Found

The server correctly creates one shared STT adapter for the whole process; it does not normally
load one model per WebSocket session. Two concurrency gaps could nevertheless multiply native
peak memory:

1. The first model load ran in `asyncio.to_thread` without cancellation shielding. Disconnecting
   or refreshing during that load released the async lock while the native thread continued.
   A new session could start a second model load.
2. A canceled transcription also left its executor thread running. The next session could begin
   another transcription against the same model before the old native call finished.
3. Separate sessions had no adapter-level transcription lock.

A controlled reproduction produced two concurrent native loads and two concurrent native
inferences after cancellation. With only about 1.1 GB of commit headroom, either overlap can turn
otherwise marginal memory pressure into `mkl_malloc`.

## Implemented Controls

- A ready local `base.en` model is loaded once during server startup, before interviews begin.
- Model loading is cancellation-shielded and drained before its lock is released.
- All calls through the shared STT adapter are serialized.
- Canceled transcription calls are drained before another caller acquires the adapter.
- The low-memory CPU default is two STT threads instead of four.
- MKL allocation failures now include current Windows physical-memory and commit-headroom values
  plus actionable page-file guidance.
- `/health` reports `sttReady` and `sttLoaded`.

These controls remove application-created overlap. They cannot manufacture memory when other
applications or system allocations have already consumed the Windows commit limit.

## Operational Fix

Before starting the real local server:

1. Stop duplicate `voice-interviewer`, Python, model benchmark, or test processes.
2. Close or restart memory-heavy browser, VS Code, Docker/WSL, VM, and local-model processes.
3. Keep Windows virtual memory **System managed**, or increase the page file from
   **System Properties -> Advanced -> Performance -> Advanced -> Virtual memory** and restart if
   Windows requests it.
4. Keep these settings for the 8 GB machine:

```text
VOICE_STT_MODEL=base.en
VOICE_STT_DEVICE=cpu
VOICE_STT_COMPUTE_TYPE=int8
VOICE_STT_CPU_THREADS=2
```

5. Start the server only after freeing several GB of commit headroom. The model now preloads, so an
   unsafe state fails at startup instead of during the first live answer.

`tiny.en` is a last-resort lower-memory model, not the preferred fix here. Redownloading
`base.en`, moving it to another drive, calling Python garbage collection, or changing the audio
sample text does not address commit exhaustion.

## Check Current Headroom

```powershell
$paths = @(
  '\Memory\Available MBytes',
  '\Memory\Committed Bytes',
  '\Memory\Commit Limit'
)
Get-Counter $paths | Select-Object -ExpandProperty CounterSamples |
  Select-Object Path, CookedValue
```

For byte-valued counters, divide `CookedValue` by `1MB`. Required headroom varies with thread
count, utterance length, and other models, so this is a diagnostic rather than a fixed admission
threshold.
