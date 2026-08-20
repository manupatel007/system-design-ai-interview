from __future__ import annotations

import pytest

from voice_interviewer.llm.mock import MockInterviewLLM
from voice_interviewer.pipeline import InterviewSessionPipeline
from voice_interviewer.stt.mock import MockSTT
from voice_interviewer.tts.mock import ToneMockTTS
from voice_interviewer.vad.energy import EnergyVad


@pytest.mark.asyncio
async def test_pipeline_accepts_structured_diagram_snapshot(mock_settings) -> None:
    events: list[dict[str, object]] = []

    async def capture(event: dict[str, object]) -> None:
        events.append(event)

    pipeline = InterviewSessionPipeline(
        session_id="diagram-session",
        settings=mock_settings,
        stt=MockSTT(),
        llm=MockInterviewLLM(),
        tts=ToneMockTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    await pipeline.handle_control({"type": "canvas.snapshot", "payload": _snapshot()})

    synced = events[-1]
    assert synced["type"] == "canvas.synced"
    assert synced["payload"] == {
        "revision": 3,
        "nodeCount": 2,
        "edgeCount": 1,
        "assistantNodeCount": 0,
        "assistantEdgeCount": 0,
        "selectedObjectIds": ["db"],
    }
    assert pipeline._client.diagram_snapshot is not None
    assert pipeline._client.recent_diagram_delta == "Connected API to database"
    assert "PostgreSQL" in (pipeline._stt_hotwords() or "")
    assert "System design interview" not in (pipeline._stt_hotwords() or "")
    await pipeline.close()


@pytest.mark.asyncio
async def test_pipeline_syncs_assistant_layer_without_candidate_activity(
    mock_settings,
) -> None:
    events: list[dict[str, object]] = []

    async def capture(event: dict[str, object]) -> None:
        events.append(event)

    pipeline = InterviewSessionPipeline(
        session_id="assistant-diagram-session",
        settings=mock_settings,
        stt=MockSTT(),
        llm=MockInterviewLLM(),
        tts=ToneMockTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    payload = _snapshot()
    payload["delta"] = {
        "addedIds": [],
        "updatedIds": [],
        "removedIds": [],
        "summary": "",
    }
    payload["assistantLayer"] = {
        "nodes": [
            {
                "id": "ai-lb",
                "shape": "rectangle",
                "role": "load_balancer",
                "label": "Load Balancer",
                "x": 500,
                "y": 0,
                "width": 160,
                "height": 80,
                "groupIds": [],
            }
        ],
        "edges": [
            {
                "id": "ai-api-lb",
                "shape": "arrow",
                "label": "HTTPS",
                "sourceId": "api",
                "targetId": "ai-lb",
                "groupIds": [],
            }
        ],
    }
    payload["selectedObjectIds"] = ["ai-lb"]

    await pipeline.handle_control({"type": "canvas.snapshot", "payload": payload})

    synced = events[-1]
    assert synced["payload"]["assistantNodeCount"] == 1
    assert synced["payload"]["assistantEdgeCount"] == 1
    assert pipeline._client.diagram_snapshot is not None
    assert pipeline._client.diagram_snapshot.selected_object_ids == ("ai-lb",)
    assert pipeline._client.recent_diagram_delta is None
    assert pipeline._client.last_canvas_activity_at == 0.0
    await pipeline.close()


@pytest.mark.asyncio
async def test_pipeline_rejects_invalid_diagram_snapshot(mock_settings) -> None:
    events: list[dict[str, object]] = []

    async def capture(event: dict[str, object]) -> None:
        events.append(event)

    pipeline = InterviewSessionPipeline(
        session_id="invalid-diagram",
        settings=mock_settings,
        stt=MockSTT(),
        llm=MockInterviewLLM(),
        tts=ToneMockTTS(),
        vad=EnergyVad(),
        send_event=capture,
    )
    await pipeline.start()
    payload = _snapshot()
    payload["edges"][0]["targetId"] = "missing"
    await pipeline.handle_control({"type": "canvas.snapshot", "payload": payload})

    assert events[-1]["type"] == "error"
    assert events[-1]["payload"]["code"] == "invalid_diagram"
    await pipeline.close()


def _snapshot() -> dict[str, object]:
    return {
        "version": 1,
        "revision": 3,
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
                "id": "db",
                "shape": "ellipse",
                "role": "database",
                "label": "PostgreSQL",
                "x": 260,
                "y": 0,
                "width": 160,
                "height": 80,
                "groupIds": [],
            },
        ],
        "edges": [
            {
                "id": "edge",
                "shape": "arrow",
                "label": "SQL",
                "sourceId": "api",
                "targetId": "db",
                "groupIds": [],
            }
        ],
        "groups": [],
        "selectedObjectIds": ["db"],
        "delta": {
            "addedIds": ["edge"],
            "updatedIds": [],
            "removedIds": [],
            "summary": "Connected API to database",
        },
    }
