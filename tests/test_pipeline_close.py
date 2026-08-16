from __future__ import annotations

import asyncio

import numpy as np
import pytest

from voice_interviewer.audio import float32_to_pcm16
from voice_interviewer.llm.mock import MockInterviewLLM
from voice_interviewer.pipeline import InterviewSessionPipeline
from voice_interviewer.tts.mock import ToneMockTTS
from voice_interviewer.vad.energy import EnergyVad


class SlowSTT:
    async def transcribe(self, audio, *, prompt=None):
        await asyncio.sleep(60)


@pytest.mark.asyncio
async def test_close_cancels_inflight_transcription_without_late_events(mock_settings) -> None:
    events = []

    async def capture(event):
        events.append(event)

    pipeline = InterviewSessionPipeline(
        session_id="closing-session",
        settings=mock_settings,
        stt=SlowSTT(),
        llm=MockInterviewLLM(),
        tts=ToneMockTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    speech = np.full(512 * 3, 0.1, dtype=np.float32)
    silence = np.zeros(512 * 3, dtype=np.float32)
    await pipeline.handle_audio(float32_to_pcm16(np.concatenate((speech, silence))))
    await asyncio.sleep(0)

    await asyncio.wait_for(pipeline.close(), timeout=1)
    event_count = len(events)
    await asyncio.sleep(0.01)

    assert len(events) == event_count
    assert "candidate.transcript.final" not in [event["type"] for event in events]
