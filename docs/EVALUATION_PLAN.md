# Voice Pipeline Evaluation Plan

## Purpose

Validate that the local voice pipeline is accurate, patient, fast, and fair enough for system-design interviews. General STT word error rate alone is insufficient: an interview can fail even with a good average score if architecture terms are corrupted or the AI repeatedly interrupts thoughtful pauses.

## Test Corpus

Build a consented, de-identified corpus with synchronized audio, expected transcript, and expected turn boundaries.

Minimum MVP composition:

| Category | Minimum examples |
| --- | ---: |
| Clean laptop microphone | 40 |
| Expected Indian-English accents | 40 |
| Other expected English accents | 40 |
| Background fan/keyboard/room noise | 30 |
| Long mid-sentence thinking pauses | 30 |
| Speech while actively drawing | 30 |
| Structured canvas edit sequences | 30 |
| Clarification, meta-question, and partial-answer sequences | 30 |
| Technical terms and acronyms | 50 |
| Barge-in during interviewer playback | 25 |
| Pure silence and non-speech noise | 25 |

Some clips should cover multiple categories. Keep a separate holdout set that is never used for threshold tuning.

## Technical Vocabulary Set

Include isolated and sentence-context instances of:

```text
Kafka, RabbitMQ, Cassandra, DynamoDB, PostgreSQL, Redis
Kubernetes, gRPC, WebSocket, CDN, QPS, RPS, p95, p99
sharding, partitioning, replication, idempotency
consistent hashing, write-ahead log, change data capture
at-least-once, exactly-once, eventual consistency
```

Generate problem-specific glossary variants and test both with and without Whisper initial prompting.

## Metrics

### Transcription

- Word error rate.
- Critical-term recall and exact spelling.
- Number and entity error rate.
- Empty transcript rate on valid speech.
- Hallucinated word rate on silence/noise.
- Final transcription latency measured from actual speech end.

### Turn Detection

- Premature endpoint rate.
- Late endpoint rate.
- False speech-start rate from keyboard, fan, or assistant audio.
- Missed speech-start rate.
- Explicit drawing-hold recognition rate.
- Percentage of responses started during active canvas work.

### Canvas Semantics

- Exact node, edge, label, group, binding, and selection extraction on fixture scenes.
- False semantic changes caused by viewport movement, zoom, or visual-only state.
- Role-inference accuracy on the expected component vocabulary.
- Rejected dangling references, contradictory groups, and unsupported schema versions.
- Snapshot-to-provider-context latency and serialized prompt size.
- Percentage of interviewer claims grounded in the latest accepted diagram revision.

### Conversation

- End of candidate turn to first assistant audio.
- Barge-in cancellation latency.
- Duplicate or stale interviewer response rate.
- Active-question continuity after partial, irrelevant, or meta-question turns.
- Direct-answer rate for candidate clarification and diagram questions.
- Unsupported phase transition rate.
- Percentage of acknowledgements grounded in actual candidate reasoning.
- Percentage of questions grounded in actual transcript/diagram evidence.
- Percentage of rubric upgrades backed by transcript or combined reasoning evidence.
- Final-feedback distinction between weak, incorrect, and not-discussed evidence.
- Human rating of timing, relevance, and concision.

Scripted fixtures should include “Can you see my diagram?”, “Can you repeat that?”, irrelevant answers, strong answers, partial answers, contradictions, uncertainty, active drawing, explicit finish, and a final transcript flushed immediately before finish.

### Speech Synthesis

- Kokoro model load time and warm synthesis real-time factor.
- Time from final response text to the first playable audio sample.
- Critical technical-term pronunciation accuracy.
- Human ratings for clarity, pace, naturalness, and interviewer tone.
- Clipping, empty audio, or unexpected sample-rate incidence.

### Reliability

- Session startup success rate.
- Model warm-load time and memory.
- CPU utilization and real-time factor.
- WebSocket reconnect behavior.
- Error rate per pipeline stage.

## Initial Acceptance Gates

These are product hypotheses to validate, not universal benchmarks:

| Metric | MVP gate |
| --- | ---: |
| Overall WER on target corpus | at most 15% |
| Critical technical-term recall | at least 95% |
| Hallucinated transcript on silence | 0 in holdout set |
| Premature turn endpoint rate | below 3% |
| Response started during active drawing | below 1% |
| Semantic extraction on checked-in fixtures | 100% |
| Invalid diagram references accepted | 0 |
| Deterministic diagram questions answered directly | 100% |
| Current question preserved across meta-questions | 100% |
| Non-adjacent phase transitions accepted | 0 |
| Diagram-only rubric upgrades accepted | 0 |
| Spoken questions per interviewer turn | at most 1 |
| Barge-in playback stop p95 | below 200 ms |
| Final STT decode p95 on target CPU | below 600 ms |
| Turn end to first assistant audio p95 | below 2 seconds |
| Local Kokoro smoke success | 100% on supported development machines |
| Critical-term pronunciation approval | at least 95% in human review |

If `base.en` misses the critical-term gate, test in this order:

1. Improve audio capture and noise handling.
2. Add a smaller, more relevant dynamic glossary.
3. Compare beam-search and decoding settings.
4. Move to `small.en` on the same runtime.
5. Compare a managed streaming STT provider.

Do not silently rewrite evidence to make a weak transcript appear correct.

## Replay Harness

The next evaluation utility should:

1. Read WAV plus a JSON sidecar containing transcript and expected turn boundaries.
2. Stream 32 ms frames through the real VAD and segmenter.
3. Run final utterances through the selected STT adapter.
4. Record every event and monotonic timestamp as JSONL.
5. Calculate transcription and turn metrics.
6. Produce aggregate and per-accent breakdowns.
7. Compare results against a checked-in baseline without storing private audio in Git.
8. Replay timestamped `canvas.snapshot` fixtures alongside audio and record the accepted revision used for each LLM turn.

Example sidecar:

```json
{
  "audio": "sample-001.wav",
  "expectedTranscript": "I would put Redis in front of PostgreSQL.",
  "criticalTerms": ["Redis", "PostgreSQL"],
  "turns": [{ "startMs": 420, "endMs": 3810 }],
  "tags": ["indian-english", "technical", "thinking-pause"]
}
```

## Human Review

At least two experienced system-design interviewers should review replayed sessions without seeing the model configuration. Rate:

- Whether interruptions felt natural.
- Whether questions referenced the correct component or claim.
- Whether the interviewer waited appropriately during drawing.
- Whether speech sounded concise and professional.
- Whether transcript mistakes affected candidate scoring.

Disagreements should be retained as uncertainty rather than forced into a single ground truth.

## Privacy Rules

- Obtain explicit consent for recorded evaluation audio.
- Remove names and identifying content where possible.
- Store audio outside Git with access controls and retention limits.
- Use stable anonymous speaker IDs for fairness analysis.
- Do not use candidate evaluation audio to train models without separate consent.
- Report aggregate accent results; do not infer nationality or ethnicity from speech.
