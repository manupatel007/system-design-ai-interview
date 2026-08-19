from __future__ import annotations

import asyncio

import numpy as np
import pytest

from voice_interviewer.audio import float32_to_pcm16
from voice_interviewer.llm.mock import MockInterviewLLM
from voice_interviewer.models import AudioOutput
from voice_interviewer.pipeline import InterviewSessionPipeline
from voice_interviewer.stt.mock import MockSTT
from voice_interviewer.tts.mock import ToneMockTTS
from voice_interviewer.vad.energy import EnergyVad


@pytest.mark.asyncio
async def test_pipeline_runs_complete_mock_turn(mock_settings) -> None:
    events = []
    completed = asyncio.Event()

    async def capture(event):
        events.append(event)
        if event["type"] == "assistant.response.completed":
            completed.set()

    pipeline = InterviewSessionPipeline(
        session_id="test-session",
        settings=mock_settings,
        stt=MockSTT("I would add a cache before the database."),
        llm=MockInterviewLLM(),
        tts=ToneMockTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    speech = np.full(512 * 3, 0.1, dtype=np.float32)
    silence = np.zeros(512 * 3, dtype=np.float32)

    await pipeline.handle_audio(float32_to_pcm16(np.concatenate((speech, silence))))
    await asyncio.wait_for(completed.wait(), timeout=3)
    await pipeline.close()

    event_types = [event["type"] for event in events]
    assert event_types[:2] == ["session.ready", "candidate.speech.started"]
    assert "candidate.transcript.final" in event_types
    assert "assistant.text.final" in event_types
    assert "assistant.audio.chunk" in event_types
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_pipeline_rejects_empty_low_confidence_transcript(mock_settings) -> None:
    events = []

    async def capture(event):
        events.append(event)

    pipeline = InterviewSessionPipeline(
        session_id="rejected-transcript-session",
        settings=mock_settings,
        stt=MockSTT(""),
        llm=MockInterviewLLM(),
        tts=ToneMockTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    speech = np.full(512 * 3, 0.1, dtype=np.float32)
    silence = np.zeros(512 * 3, dtype=np.float32)

    await pipeline.handle_audio(float32_to_pcm16(np.concatenate((speech, silence))))
    await asyncio.wait_for(pipeline._transcription_queue.join(), timeout=1)
    await pipeline.close()

    event_types = [event["type"] for event in events]
    assert "candidate.transcript.rejected" in event_types
    assert "candidate.transcript.final" not in event_types
    assert "assistant.response.started" not in event_types


class LongPlaybackTTS:
    async def synthesize(self, text: str) -> AudioOutput:
        return AudioOutput(pcm_s16le=bytes(16_000 * 2 * 10), sample_rate=16_000)


class ChunkedTTS:
    async def synthesize(self, text: str) -> AudioOutput:
        raise AssertionError("Pipeline should prefer sentence streaming")

    async def synthesize_stream(self, text: str):
        yield AudioOutput(pcm_s16le=bytes(160), sample_rate=16_000)
        yield AudioOutput(pcm_s16le=bytes(320), sample_rate=16_000)


@pytest.mark.asyncio
async def test_pipeline_emits_streamed_tts_chunks_in_order(mock_settings) -> None:
    events = []
    completed = asyncio.Event()

    async def capture(event):
        events.append(event)
        if event["type"] == "assistant.response.completed":
            completed.set()

    pipeline = InterviewSessionPipeline(
        session_id="streamed-tts-session",
        settings=mock_settings,
        stt=MockSTT("I would add a cache."),
        llm=MockInterviewLLM(),
        tts=ChunkedTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    speech = np.full(512 * 3, 0.1, dtype=np.float32)
    silence = np.zeros(512 * 3, dtype=np.float32)

    await pipeline.handle_audio(float32_to_pcm16(np.concatenate((speech, silence))))
    await asyncio.wait_for(completed.wait(), timeout=3)
    await pipeline.close()

    chunks = [event for event in events if event["type"] == "assistant.audio.chunk"]
    assert [chunk["payload"]["chunkIndex"] for chunk in chunks] == [0, 1]


@pytest.mark.asyncio
async def test_candidate_speech_interrupts_playback_window(mock_settings) -> None:
    events = []
    audio_sent = asyncio.Event()
    interrupted = asyncio.Event()

    async def capture(event):
        events.append(event)
        if event["type"] == "assistant.audio.chunk":
            audio_sent.set()
        elif event["type"] == "assistant.interrupted":
            interrupted.set()

    pipeline = InterviewSessionPipeline(
        session_id="barge-in-session",
        settings=mock_settings,
        stt=MockSTT("I would place a cache before the database."),
        llm=MockInterviewLLM(),
        tts=LongPlaybackTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    speech = np.full(512 * 3, 0.1, dtype=np.float32)
    silence = np.zeros(512 * 3, dtype=np.float32)

    await pipeline.handle_audio(float32_to_pcm16(np.concatenate((speech, silence))))
    await asyncio.wait_for(audio_sent.wait(), timeout=3)
    await pipeline.handle_audio(float32_to_pcm16(speech))
    await asyncio.wait_for(interrupted.wait(), timeout=1)
    await pipeline.close()

    event_types = [event["type"] for event in events]
    assert "assistant.interrupted" in event_types
    assert "assistant.response.completed" not in event_types
