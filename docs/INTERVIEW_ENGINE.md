# Structured Interview Engine

## Objective

The interview must behave like one continuous conversation rather than a sequence of unrelated prompts. Each WebSocket session therefore owns an authoritative interview state. The remote or mock model proposes a typed turn plan; a deterministic reducer validates and applies it before anything is spoken.

```text
final transcript + latest diagram
  -> deterministic dialogue and help-policy guards
  -> compact interview state
  -> structured provider plan
  -> phase and evidence policy
  -> state reducer
  -> one short spoken response
  -> interview.state / interview.feedback events
```

Provider adapters remain stateless and may be shared across sessions. `StructuredInterviewEngine` is created per session, so candidates cannot leak history or rubric state into one another.

## Why the Previous Behavior Felt Random

The original adapter received only the latest transcript and diagram and was instructed to ask one follow-up question. It did not know:

- Which question it had just asked.
- Whether the candidate answered it fully or partially.
- Which phase of the interview was active.
- What evidence had already been demonstrated.
- Whether the candidate was asking the interviewer a question.

The model consequently treated almost every utterance as permission to generate another technical probe. The structured engine makes those facts explicit and prevents non-adjacent phase jumps.

## Session State

The bounded provider context contains:

- Current phase and turns spent in that phase.
- Current question, topic, expected competency evidence, and answer status.
- Candidate assumptions and design decisions.
- Covered topics.
- Evidence ledger entries with source and supporting diagram object IDs.
- Rubric coverage for nine competencies.
- The last six conversation turns and last twelve evidence entries.
- Assistance policy plus recent scoped help disclosures.
- Phase history and completion state.

The browser receives a slightly richer state projection with up to twenty recent evidence entries. Full audio is never included or persisted.

## Interview Phases

Progression is ordered but evidence-driven:

1. `introduction`
2. `requirements`
3. `estimation`
4. `high_level_design`
5. `deep_dive`
6. `reliability_and_scale`
7. `wrap_up`
8. `complete`

A provider may keep the current phase or request the next adjacent phase. It cannot skip phases. The reducer advances when the phase's target competency has evidence; after three turns it may advance flexibly so an irrelevant phase does not trap the interview.

## Question Threading

Every active question has:

- A stable question ID.
- The exact text the candidate heard.
- A topic.
- Expected competency evidence.
- `unanswered`, `partial`, `answered`, or `not_applicable` status.

The provider must classify the candidate turn before selecting an action. Supported intents include answers, partial answers, clarification requests, explicit help requests, meta-questions, diagram questions, drawing explanations, uncertainty, off-topic speech, and finish requests.

The response policy requires:

- A specific acknowledgement when evidence was supplied.
- A targeted follow-up when only part of the question was answered.
- No generic unrelated probe.
- At most one question per spoken response.
- An adjacent phase transition only after relevant evidence.

## Scoped Progressive Assistance

Practice support is configured per session:

| Policy | First request | Repeated request |
| --- | --- | --- |
| `strict` | Nudge | Nudge |
| `adaptive` | Nudge | Concept, then bounded example |
| `guided` | Concept | Bounded example |

Help is explicit rather than a separate tutor mode. The engine recognizes direct phrases such as
"I need a hint", computes a scope from the active question and validated selected canvas IDs, and
places a trusted assistance directive beside the untrusted interview evidence. The provider may
explain only to the selected depth and may attach grounded focus references.

The reducer then forces the turn to `help_request`/`assist`, keeps the current question and phase,
and strips every evidence, rubric, assumption, decision, and covered-topic update. Help turns also
do not increment `phaseTurns`, so repeated coaching cannot silently advance the interview. The
history remains visible for reflection and final feedback, while only subsequent candidate
reasoning can become evidence.

## Deterministic Conversation Repairs

High-confidence interaction repairs do not require a provider call:

- “Can you see my diagram?” is answered from the accepted snapshot, naming only real nodes and the first bound relationship.
- “Can you repeat the question?” repeats the active question and preserves its status.
- Explicit finish phrases enter finalization.

For example, given `API -> Redis -> PostgreSQL`, the interviewer can say:

```text
Yes—I can see API, Redis, and PostgreSQL, with API connected to Redis.
The diagram is coming through clearly; please continue.
```

The active technical question remains open instead of being replaced by a random probe.

## Structured Provider Plan

Databricks Responses and Azure Foundry Chat Completions receive the same strict JSON Schema. Each plan contains:

- Candidate intent, selected action, and current-question status, including explicit assistance.
- Acknowledgement and final spoken utterance.
- Evidence, rubric, assumption, decision, and covered-topic updates.
- Requested next phase.
- Optional next question represented by an empty or populated required object.
- Optional final feedback represented by required fields with empty defaults.
- Up to three grounded canvas references, or an empty required array.

The gateway parses JSON and the interview model validates types, enums, fields, lengths, and array limits again locally. Malformed plans become secret-safe `response_failed` events rather than partially mutating session state.

## Evidence and Rubric Policy

The live rubric tracks coverage, not a final numeric score:

- `not_observed`
- `some_evidence`
- `demonstrated`

Nine competency dimensions cover requirements, estimation, API/data modeling, architecture, scalability, reliability, consistency, security/observability, and communication/trade-offs.

Evidence is recorded as `transcript`, `diagram`, or `combined`. Diagram-only evidence may be retained for grounding, but it cannot upgrade rubric coverage. A cache rectangle is not proof that the candidate understands cache invalidation. Rubric updates require transcript or combined reasoning evidence, and levels can only move upward during the live interview. Assistance turns are non-evidentiary even if a provider proposes updates.

Final feedback separates:

- Demonstrated strengths.
- Specific areas to improve.
- Competencies not discussed.

It does not invent a score or label an unvisited topic as incorrect.

## Finish Behavior

The browser's **Finish interview** action:

1. Stops and flushes the microphone.
2. Waits for queued local transcription.
3. Force-consumes the final transcript without waiting for the normal canvas gate.
4. Cancels any active response and playback.
5. Requests a `complete` plan with no next question.
6. Emits `interview.feedback` and a final `interview.state`.

The meeting-style UI keeps the current phase and active question on the interviewer card, retains both speakers in a scrollable transcript, and shows final feedback in the transcript pane. Detailed evidence, rubric, and state projections remain available through the event protocol for tests, evaluation tooling, and future reviewer views rather than occupying the candidate workspace.

## Bounds and Safety

- Candidate transcript, diagram content, and evidence JSON are explicitly untrusted; only the server-created turn mode and runtime directive are trusted.
- Diagram object IDs in evidence are intersected with the accepted snapshot.
- Canvas feedback IDs are independently intersected with the accepted snapshot before emission.
- Assistance scopes use validated selected IDs, and assisted content cannot create evidence.
- Diagram-only evidence cannot change the rubric.
- Phase transitions are adjacent and reducer-controlled.
- Assumptions, decisions, topics, prompt history, labels, and plan arrays are bounded.
- Provider errors contain no prompts, response bodies, credentials, or authorization headers.
- Active state remains in memory and is discarded at session close.

## Validation

The test suite covers:

- Coherent mock progression across all phases.
- Irrelevant and partial answers retaining the current thread.
- Diagram visibility questions bypassing the provider and preserving the question ID.
- Grounded canvas references filtering invented IDs and preserving event order.
- Scoped help escalation, policy differences, question preservation, and evidence isolation.
- Assumption, decision, topic, evidence, and rubric updates.
- Rejected phase skips.
- Diagram-only evidence not upgrading a rubric.
- Evidence-backed final feedback with `not discussed` distinctions.
- Databricks and Azure structured-plan wire contracts.
- Full WebSocket/pipeline behavior from diagram question through finish.

```powershell
. .\scripts\env.ps1
uv run pytest tests\test_interview_engine.py tests\test_pipeline_conversation.py
```
