from __future__ import annotations

import asyncio

import numpy as np
import pytest

from voice_interviewer.audio import float32_to_pcm16
from voice_interviewer.llm.mock import MockInterviewLLM
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
