from __future__ import annotations

import re
from dataclasses import dataclass, field

_HOLD_PATTERN = re.compile(
    r"\b(let me|i(?:'|’)ll|i will)\s+(draw|sketch|diagram|think)|give me a (moment|second)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class TurnGate:
    canvas_quiet_seconds: float
    explicit_hold_seconds: float
    response_debounce_seconds: float = 0.15
    candidate_speaking: bool = False
    last_canvas_activity_at: float = 0.0
    last_turn_update_at: float = 0.0
    explicit_hold_until: float = 0.0
    ready_at: float | None = None
    _transcript_parts: list[str] = field(default_factory=list)

    def on_speech_started(self, now: float) -> None:
        self.candidate_speaking = True
        self.last_turn_update_at = now
        self.ready_at = None

    def on_speech_ended(self, now: float) -> None:
        self.candidate_speaking = False
        self.last_turn_update_at = now
        self._recalculate()

    def on_transcript(self, text: str, now: float) -> None:
        normalized = text.strip()
        if not normalized:
            return
        self._transcript_parts.append(normalized)
        self.last_turn_update_at = now
        if _HOLD_PATTERN.search(normalized):
            self.explicit_hold_until = max(
                self.explicit_hold_until, now + self.explicit_hold_seconds
            )
        self._recalculate()

    def on_canvas_activity(self, now: float) -> None:
        self.last_canvas_activity_at = now
        self._recalculate()

    def seconds_until_ready(self, now: float) -> float | None:
        self._recalculate()
        if self.ready_at is None:
            return None
        return max(0.0, self.ready_at - now)

    def consume(self, now: float) -> str | None:
        remaining = self.seconds_until_ready(now)
        if remaining is None or remaining > 0:
            return None
        transcript = " ".join(self._transcript_parts)
        self._transcript_parts.clear()
        self.ready_at = None
        self.explicit_hold_until = 0.0
        return transcript

    def _recalculate(self) -> None:
        if self.candidate_speaking or not self._transcript_parts:
            self.ready_at = None
            return
        ready_at = self.last_turn_update_at + self.response_debounce_seconds
        if self.last_canvas_activity_at:
            ready_at = max(
                ready_at, self.last_canvas_activity_at + self.canvas_quiet_seconds
            )
        self.ready_at = max(ready_at, self.explicit_hold_until)
