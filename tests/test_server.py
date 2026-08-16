from __future__ import annotations

from fastapi.testclient import TestClient

from voice_interviewer.server import create_app


def test_health_and_static_client(mock_settings) -> None:
    with TestClient(create_app(mock_settings)) as client:
        health = client.get("/health")
        index = client.get("/")

    assert health.status_code == 200
    assert health.json()["backends"]["stt"] == "mock"
    assert index.status_code == 200
    assert "System Design Voice Interviewer" in index.text


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

    assert ready["type"] == "session.ready"
    assert configured["type"] == "session.configured"
