from __future__ import annotations

import asyncio
from dataclasses import replace

import numpy as np
import pytest

from voice_interviewer.audio import float32_to_pcm16
from voice_interviewer.llm.mock import MockInterviewLLM
from voice_interviewer.models import AudioOutput, InterviewContext
from voice_interviewer.pipeline import InterviewSessionPipeline
from voice_interviewer.stt.mock import MockSTT
from voice_interviewer.vad.energy import EnergyVad


class InstantTTS:
    async def synthesize(self, text: str) -> AudioOutput:
        return AudioOutput(pcm_s16le=b"", sample_rate=16_000)


class CapturingMockLLM(MockInterviewLLM):
    def __init__(self) -> None:
        self.final_transcript = ""

    async def plan(self, context: InterviewContext):
        if context.turn_mode == "finalize":
            self.final_transcript = context.transcript
        return await super().plan(context)


@pytest.mark.asyncio
async def test_pipeline_answers_diagram_meta_question_and_finishes_coherently(
    mock_settings,
) -> None:
    events: list[dict[str, object]] = []

    async def capture(event: dict[str, object]) -> None:
        events.append(event)

    pipeline = InterviewSessionPipeline(
        session_id="structured-conversation",
        settings=mock_settings,
        stt=MockSTT("Can you see my diagram?"),
        llm=MockInterviewLLM(),
        tts=InstantTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    await pipeline.handle_control(
        {
            "type": "session.configure",
            "payload": {"problem": "Design a URL shortener", "glossary": ["Redis"]},
        }
    )
    await _wait_for_event(events, "assistant.response.completed", count=1)
    initial_state = _events(events, "interview.state")[-1]["payload"]
    assert initial_state["phase"] == "requirements"
    question_id = initial_state["currentQuestion"]["id"]

    await pipeline.handle_control(
        {"type": "canvas.snapshot", "payload": _diagram_snapshot()}
    )
    speech = np.full(512 * 3, 0.1, dtype=np.float32)
    silence = np.zeros(512 * 3, dtype=np.float32)
    await pipeline.handle_audio(float32_to_pcm16(np.concatenate((speech, silence))))
    await _wait_for_event(events, "assistant.response.completed", count=2)

    diagram_response = _events(events, "assistant.text.final")[-1]["payload"]["text"]
    diagram_state = _events(events, "interview.state")[-1]["payload"]
    assert "Yes—I can see API, Redis" in diagram_response
    assert "API connected to Redis" in diagram_response
    assert diagram_response.endswith("please continue.")
    assert diagram_state["currentQuestion"]["id"] == question_id
    assert diagram_state["evidenceCount"] == 0

    await pipeline.handle_control({"type": "interview.finish", "payload": {}})
    feedback = await _wait_for_event(events, "interview.feedback")
    final_state = _events(events, "interview.state")[-1]["payload"]
    assert feedback["payload"]["summary"]
    assert "Requirements and scope" in feedback["payload"]["notDiscussed"]
    assert final_state["phase"] == "complete"
    assert final_state["completed"] is True
    await pipeline.close()


@pytest.mark.asyncio
async def test_finish_waits_for_and_includes_final_transcript(mock_settings) -> None:
    events: list[dict[str, object]] = []
    llm = CapturingMockLLM()

    async def capture(event: dict[str, object]) -> None:
        events.append(event)

    pipeline = InterviewSessionPipeline(
        session_id="finish-with-transcript",
        settings=replace(mock_settings, canvas_quiet_ms=5_000),
        stt=MockSTT("My final improvement is regional failover."),
        llm=llm,
        tts=InstantTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    await pipeline.handle_control(
        {
            "type": "session.configure",
            "payload": {"problem": "Design a URL shortener"},
        }
    )
    await _wait_for_event(events, "assistant.response.completed")

    await pipeline.handle_control(
        {"type": "canvas.activity", "payload": {"diagramDelta": "editing"}}
    )
    speech = np.full(512 * 3, 0.1, dtype=np.float32)
    silence = np.zeros(512 * 3, dtype=np.float32)
    await pipeline.handle_audio(float32_to_pcm16(np.concatenate((speech, silence))))
    await pipeline.handle_control({"type": "interview.finish", "payload": {}})
    await _wait_for_event(events, "interview.feedback")

    assert llm.final_transcript == "My final improvement is regional failover."
    assert _events(events, "candidate.transcript.final")[-1]["payload"]["text"] == (
        "My final improvement is regional failover."
    )
    await pipeline.close()


async def _wait_for_event(
    events: list[dict[str, object]],
    event_type: str,
    *,
    count: int = 1,
) -> dict[str, object]:
    for _ in range(300):
        matches = _events(events, event_type)
        if len(matches) >= count:
            return matches[count - 1]
        await asyncio.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {event_type}")


def _events(
    events: list[dict[str, object]], event_type: str
) -> list[dict[str, object]]:
    return [event for event in events if event["type"] == event_type]


def _diagram_snapshot() -> dict[str, object]:
    return {
        "version": 1,
        "revision": 1,
        "nodes": [
            {
                "id": "api",
                "shape": "rectangle",
                "role": "service",
                "label": "API",
                "x": 0,
                "y": 0,
                "width": 160,
                "height": 80,
                "groupIds": [],
            },
            {
                "id": "cache",
                "shape": "rectangle",
                "role": "cache",
                "label": "Redis",
                "x": 240,
                "y": 0,
                "width": 160,
                "height": 80,
                "groupIds": [],
            },
        ],
        "edges": [
            {
                "id": "api-cache",
                "shape": "arrow",
                "label": "lookup",
                "sourceId": "api",
                "targetId": "cache",
                "groupIds": [],
            }
        ],
        "groups": [],
        "selectedObjectIds": ["cache"],
        "delta": {
            "addedIds": ["api", "cache", "api-cache"],
            "updatedIds": [],
            "removedIds": [],
            "summary": "Connected API to Redis",
        },
    }
