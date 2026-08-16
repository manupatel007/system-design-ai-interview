from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from voice_interviewer.diagram import DiagramSnapshot


@dataclass(slots=True)
class EventFactory:
    session_id: str
    sequence: int = 0

    def create(self, event_type: str, **payload: Any) -> dict[str, Any]:
        self.sequence += 1
        return {
            "type": event_type,
            "sessionId": self.session_id,
            "sequence": self.sequence,
            "timestampMs": round(time.time() * 1000),
            "payload": payload,
        }


@dataclass(slots=True)
class ClientState:
    problem: str | None = None
    glossary: list[str] = field(default_factory=list)
    recent_diagram_delta: str | None = None
    selected_object_ids: list[str] = field(default_factory=list)
    diagram_snapshot: DiagramSnapshot | None = None
    last_canvas_activity_at: float = 0.0
