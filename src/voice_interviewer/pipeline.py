from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import numpy as np

from voice_interviewer.audio import AudioFrameBuffer, pcm16_bytes_to_float32
from voice_interviewer.config import Settings
from voice_interviewer.diagram import DiagramSnapshot, DiagramValidationError
from voice_interviewer.events import ClientState, EventFactory
from voice_interviewer.interview.engine import InterviewEngineResult, StructuredInterviewEngine
from voice_interviewer.models import (
    AudioOutput,
    InterviewContext,
    InterviewLanguageModel,
    SpeechToText,
    TextToSpeech,
    VoiceActivityDetector,
)
from voice_interviewer.turns import TurnGate
from voice_interviewer.vad.segmenter import SegmentEventType, SpeechSegmenter

SendEvent = Callable[[dict[str, object]], Awaitable[None]]


class InterviewSessionPipeline:
    def __init__(
        self,
        *,
        session_id: str,
        settings: Settings,
        stt: SpeechToText,
        llm: InterviewLanguageModel,
        tts: TextToSpeech,
        vad: VoiceActivityDetector,
        send_event: SendEvent,
    ) -> None:
        self.session_id = session_id
        self.settings = settings
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.vad = vad
        self._send_event = send_event
        self._interview = StructuredInterviewEngine(llm)
        self._events = EventFactory(session_id)
        self._client = ClientState()
        self._frames = AudioFrameBuffer(vad.frame_samples)
        self._segmenter = SpeechSegmenter(
            sample_rate=settings.sample_rate,
            frame_samples=vad.frame_samples,
            threshold=settings.vad_threshold,
            negative_threshold=settings.vad_negative_threshold,
            min_speech_ms=settings.vad_min_speech_ms,
            min_silence_ms=settings.vad_min_silence_ms,
            prefix_padding_ms=settings.vad_prefix_padding_ms,
        )
        self._turn_gate = TurnGate(
            canvas_quiet_seconds=settings.canvas_quiet_ms / 1000,
            explicit_hold_seconds=settings.explicit_hold_ms / 1000,
        )
        self._send_lock = asyncio.Lock()
        self._transcription_queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue()
        self._transcription_worker: asyncio.Task[None] | None = None
        self._response_task: asyncio.Task[None] | None = None
        self._assistant_active = False
        self._closed = False

    async def start(self) -> None:
        self._transcription_worker = asyncio.create_task(
            self._run_transcription_worker(), name=f"transcription-{self.session_id}"
        )
        await self._emit(
            "session.ready",
            sampleRate=self.settings.sample_rate,
            audioEncoding="pcm_s16le",
            sttBackend=self.settings.stt_backend,
            vadBackend=self.settings.vad_backend,
            llmBackend=self.settings.llm_backend,
            ttsBackend=self.settings.tts_backend,
        )

    async def handle_audio(self, data: bytes) -> None:
        audio = pcm16_bytes_to_float32(data)
        for frame in self._frames.push(audio):
            probability = self.vad.predict(frame)
            for event in self._segmenter.push(frame, probability):
                if event.type is SegmentEventType.SPEECH_STARTED:
                    await self._on_speech_started()
                elif event.type is SegmentEventType.SPEECH_ENDED and event.audio is not None:
                    await self._on_speech_ended(event.audio)

    async def handle_control(self, message: dict[str, object]) -> None:
        event_type = str(message.get("type", ""))
        payload = message.get("payload")
        values = payload if isinstance(payload, dict) else {}
        if event_type == "session.configure":
            self._client.problem = _optional_string(values.get("problem"))
            self._client.glossary = _string_list(values.get("glossary"))
            interview_state = self._interview.configure(
                self._client.problem,
                _optional_string(values.get("assistancePolicy")),
            )
            await self._emit("session.configured")
            await self._emit("interview.state", **interview_state)
            self._schedule_interview_start()
            return
        if event_type == "canvas.snapshot":
            try:
                snapshot = DiagramSnapshot.from_payload(values)
            except DiagramValidationError as error:
                await self._emit("error", code="invalid_diagram", message=str(error))
                return
            self._client.diagram_snapshot = snapshot
            self._client.selected_object_ids = list(snapshot.selected_object_ids)
            changed = bool(
                snapshot.delta.added_ids
                or snapshot.delta.updated_ids
                or snapshot.delta.removed_ids
            )
            if changed:
                now = time.monotonic()
                self._client.last_canvas_activity_at = now
                self._client.recent_diagram_delta = snapshot.delta.summary or (
                    f"updated diagram revision {snapshot.revision}"
                )
                self._turn_gate.on_canvas_activity(now)
            await self._emit(
                "canvas.synced",
                revision=snapshot.revision,
                nodeCount=len(snapshot.nodes),
                edgeCount=len(snapshot.edges),
                assistantNodeCount=len(snapshot.assistant_nodes),
                assistantEdgeCount=len(snapshot.assistant_edges),
                selectedObjectIds=list(snapshot.selected_object_ids),
            )
            self._schedule_response()
            return
        if event_type == "canvas.activity":
            now = time.monotonic()
            self._client.last_canvas_activity_at = now
            self._client.recent_diagram_delta = _optional_string(
                values.get("diagramDelta")
            )
            self._client.selected_object_ids = _string_list(values.get("selectedObjectIds"))
            self._turn_gate.on_canvas_activity(now)
            self._schedule_response()
            return
        if event_type == "guided.takeover.start":
            requested_scope = _optional_string(values.get("scope"))
            scope = (
                requested_scope
                if requested_scope in {"selection", "current_question", "end_to_end"}
                else (
                    "selection"
                    if self._client.selected_object_ids
                    else "current_question"
                )
            )
            context = self._interview_context()
            await self._schedule_interview_control(
                lambda: self._interview.start_guided_takeover(context, scope=scope),
                task_name="guided-takeover-start",
            )
            return
        if event_type == "guided.takeover.command":
            command = _optional_string(values.get("command")) or ""
            if command not in {"continue", "why", "alternative", "take_back", "question"}:
                await self._emit(
                    "error",
                    code="invalid_guided_takeover_command",
                    message=command or "missing command",
                )
                return
            context = self._interview_context()
            question = _optional_string(values.get("question")) or ""
            await self._schedule_interview_control(
                lambda: self._interview.guided_takeover_command(
                    context,
                    command,
                    question=question,
                ),
                task_name=f"guided-takeover-{command}",
            )
            return
        if event_type == "interview.finish":
            await self._transcription_queue.join()
            pending_transcript = self._turn_gate.force_consume() or ""
            interrupted = self._assistant_active
            if self._response_task and not self._response_task.done():
                self._response_task.cancel()
            self._assistant_active = False
            if interrupted:
                await self._emit("assistant.interrupted", reason="interview_finished")
            self._response_task = asyncio.create_task(
                self._finalize_interview(pending_transcript),
                name=f"finalize-{self.session_id}",
            )
            return
        if event_type == "audio.flush":
            await self._flush_audio()
            return
        await self._emit("error", code="unsupported_event", message=event_type)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._response_task:
            self._response_task.cancel()
        if self._transcription_worker:
            self._transcription_worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._transcription_worker
        self._segmenter.reset()
        self.vad.reset()

    async def _on_speech_started(self) -> None:
        now = time.monotonic()
        self._turn_gate.on_speech_started(now)
        interrupted = self._assistant_active
        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
        self._response_task = None
        self._assistant_active = False
        await self._emit("candidate.speech.started")
        if interrupted:
            await self._emit("assistant.interrupted", reason="candidate_speech")

    async def _on_speech_ended(self, audio: np.ndarray) -> None:
        self._turn_gate.on_speech_ended(time.monotonic())
        await self._emit(
            "candidate.speech.ended",
            durationMs=round(len(audio) / self.settings.sample_rate * 1000),
        )
        await self._transcription_queue.put(audio)

    async def _flush_audio(self) -> None:
        pending = self._frames.flush(pad=True)
        if pending is not None:
            probability = self.vad.predict(pending)
            for event in self._segmenter.push(pending, probability):
                if event.type is SegmentEventType.SPEECH_STARTED:
                    await self._on_speech_started()
                elif event.audio is not None:
                    await self._on_speech_ended(event.audio)
        final_event = self._segmenter.flush()
        if final_event and final_event.audio is not None:
            await self._on_speech_ended(final_event.audio)

    async def _run_transcription_worker(self) -> None:
        while True:
            audio = await self._transcription_queue.get()
            if audio is None:
                self._transcription_queue.task_done()
                return
            try:
                transcript = await self.stt.transcribe(audio, prompt=self._stt_hotwords())
                if not transcript.text:
                    await self._emit(
                        "candidate.transcript.rejected",
                        reason="no_reliable_speech",
                        durationMs=round(transcript.duration_seconds * 1000),
                    )
                    self._schedule_response()
                    continue
                await self._emit(
                    "candidate.transcript.final",
                    text=transcript.text,
                    language=transcript.language,
                    durationMs=round(transcript.duration_seconds * 1000),
                )
                self._turn_gate.on_transcript(transcript.text, time.monotonic())
                self._schedule_response()
            except Exception as error:
                await self._emit(
                    "error",
                    code="transcription_failed",
                    message=str(error),
                )
            finally:
                self._transcription_queue.task_done()

    def _schedule_response(self) -> None:
        if self._closed:
            return
        delay = self._turn_gate.seconds_until_ready(time.monotonic())
        if delay is None:
            return
        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
        self._response_task = asyncio.create_task(
            self._respond_after(delay), name=f"response-{self.session_id}"
        )

    def _schedule_interview_start(self) -> None:
        if self._closed:
            return
        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
        self._response_task = asyncio.create_task(
            self._start_interview_after(0.25),
            name=f"interview-start-{self.session_id}",
        )

    async def _schedule_interview_control(
        self,
        producer: Callable[[], Awaitable[InterviewEngineResult]],
        *,
        task_name: str,
    ) -> None:
        if self._closed:
            return
        interrupted = self._assistant_active
        pending = self._response_task
        if pending and not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        self._response_task = None
        self._assistant_active = False
        if interrupted:
            await self._emit("assistant.interrupted", reason="guided_takeover_control")
        self._response_task = asyncio.create_task(
            self._execute_interview(producer),
            name=f"{task_name}-{self.session_id}",
        )

    async def _respond_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        transcript = self._turn_gate.consume(time.monotonic())
        if transcript is None:
            self._schedule_response()
            return
        context = self._interview_context(transcript)
        self._client.recent_diagram_delta = None
        await self._execute_interview(lambda: self._interview.respond(context))

    async def _start_interview_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        context = self._interview_context()
        await self._execute_interview(lambda: self._interview.start(context))
        self._client.recent_diagram_delta = None

    async def _finalize_interview(self, transcript: str = "") -> None:
        context = self._interview_context(transcript)
        await self._execute_interview(lambda: self._interview.finalize(context))

    async def _execute_interview(
        self,
        producer: Callable[[], Awaitable[InterviewEngineResult]],
    ) -> None:
        try:
            self._assistant_active = True
            await self._emit("assistant.response.started")
            result = await producer()
            await self._emit("interview.state", **result.state)
            if result.feedback:
                await self._emit("interview.feedback", **result.feedback.to_dict())
            if result.assistance:
                await self._emit(
                    "assistant.assistance",
                    **result.assistance.to_dict(),
                )
            if result.canvas_references:
                await self._emit(
                    "assistant.canvas.references",
                    references=[
                        reference.to_dict() for reference in result.canvas_references
                    ],
                )
            if result.canvas_proposal:
                guided_takeover = result.state.get("guidedTakeover")
                guided_metadata = (
                    guided_takeover if isinstance(guided_takeover, dict) else None
                )
                anchor_ids = result.canvas_anchor_ids or (
                    result.assistance.object_ids if result.assistance else ()
                )
                await self._emit(
                    "assistant.canvas.proposal",
                    proposal=result.canvas_proposal.to_dict(),
                    anchorObjectIds=list(anchor_ids),
                    autoAccept=result.canvas_proposal_auto_accept,
                    guidedTakeover=guided_metadata,
                    guidedStep=(
                        guided_metadata.get("step") if guided_metadata else None
                    ),
                )
            await self._emit("assistant.text.final", text=result.text)
            playback_ends_at: float | None = None
            chunk_count = 0
            async for audio in self._synthesize_chunks(result.text):
                await self._emit(
                    "assistant.audio.chunk",
                    audio=base64.b64encode(audio.pcm_s16le).decode("ascii"),
                    encoding="pcm_s16le",
                    sampleRate=audio.sample_rate,
                    channels=audio.channels,
                    chunkIndex=chunk_count,
                )
                chunk_count += 1
                chunk_seconds = len(audio.pcm_s16le) / (
                    2 * audio.channels * audio.sample_rate
                )
                emitted_at = time.perf_counter()
                playback_ends_at = (
                    max(emitted_at, playback_ends_at or emitted_at) + chunk_seconds
                )
            if playback_ends_at is None:
                raise RuntimeError("TTS returned no audio chunks")
            await asyncio.sleep(max(0.0, playback_ends_at - time.perf_counter()))
            await self._emit("assistant.response.completed")
            self._assistant_active = False
        except asyncio.CancelledError:
            self._assistant_active = False
            raise
        except Exception as error:
            self._assistant_active = False
            await self._emit("error", code="response_failed", message=str(error))

    async def _synthesize_chunks(self, text: str) -> AsyncIterator[AudioOutput]:
        synthesize_stream = getattr(self.tts, "synthesize_stream", None)
        if synthesize_stream is None:
            yield await self.tts.synthesize(text)
            return
        async for chunk in synthesize_stream(text):
            yield chunk

    def _interview_context(self, transcript: str = "") -> InterviewContext:
        return InterviewContext(
            session_id=self.session_id,
            problem=self._client.problem,
            transcript=transcript,
            recent_diagram_delta=self._client.recent_diagram_delta,
            selected_object_ids=tuple(self._client.selected_object_ids),
            glossary=tuple(self._client.glossary),
            diagram=self._client.diagram_snapshot,
        )

    def _stt_hotwords(self) -> str | None:
        diagram_terms = (
            list(self._client.diagram_snapshot.glossary_terms())
            if self._client.diagram_snapshot
            else []
        )
        terms = list(dict.fromkeys(self._client.glossary + diagram_terms))
        if not terms:
            return None
        return ", ".join(terms[:50])

    async def _emit(self, event_type: str, **payload: object) -> None:
        if self._closed:
            return
        event = self._events.create(event_type, **payload)
        async with self._send_lock:
            await self._send_event(event)


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
