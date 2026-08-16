from __future__ import annotations

from fastapi.testclient import TestClient

from voice_interviewer.server import create_app


def test_health_and_static_client(mock_settings) -> None:
    with TestClient(create_app(mock_settings)) as client:
        health = client.get("/health")
        index = client.get("/")
        diagram_bundle = client.get("/static/excalidraw/diagram-app.js")

    assert health.status_code == 200
    assert health.json()["backends"]["stt"] == "mock"
    assert health.json()["backends"]["tts"] == "mock"
    assert index.status_code == 200
    assert "System Design Voice Interviewer" in index.text
    assert "excalidraw-root" in index.text
    assert "interview-phase" in index.text
    assert "Finish interview" in index.text
    assert diagram_bundle.status_code == 200


def test_websocket_configures_mock_session(mock_settings) -> None:
    with TestClient(create_app(mock_settings)) as client:
        with client.websocket_connect("/ws/interview/browser-test") as socket:
            ready = socket.receive_json()
            socket.send_json(
                {
                    "type": "session.configure",
                    "payload": {
                        "problem": "Design a URL shortener",
                        "glossary": ["Redis", "PostgreSQL"],
                    },
                }
            )
            configured = socket.receive_json()
            interview_state = socket.receive_json()

    assert ready["type"] == "session.ready"
    assert configured["type"] == "session.configured"
    assert interview_state["type"] == "interview.state"
    assert interview_state["payload"]["phase"] == "introduction"


def test_websocket_accepts_structured_canvas_snapshot(mock_settings) -> None:
    with TestClient(create_app(mock_settings)) as client:
        with client.websocket_connect("/ws/interview/diagram-test") as socket:
            socket.receive_json()
            socket.send_json(
                {
                    "type": "canvas.snapshot",
                    "payload": {
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
                            }
                        ],
                        "edges": [],
                        "groups": [],
                        "selectedObjectIds": ["api"],
                        "delta": {
                            "addedIds": ["api"],
                            "updatedIds": [],
                            "removedIds": [],
                            "summary": "Added API",
                        },
                    },
                }
            )
            synced = socket.receive_json()

    assert synced["type"] == "canvas.synced"
    assert synced["payload"]["nodeCount"] == 1
    assert synced["payload"]["selectedObjectIds"] == ["api"]
