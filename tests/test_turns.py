from __future__ import annotations

import pytest

from voice_interviewer.turns import TurnGate


def test_turn_waits_for_canvas_quiet_period() -> None:
    gate = TurnGate(canvas_quiet_seconds=1.5, explicit_hold_seconds=10)
    gate.on_speech_started(1.0)
    gate.on_speech_ended(2.0)
    gate.on_transcript("I added a cache.", 2.1)
    gate.on_canvas_activity(2.5)

    assert gate.seconds_until_ready(3.9) == pytest.approx(0.1)
    assert gate.consume(3.9) is None
    assert gate.consume(4.0) == "I added a cache."


def test_turn_accumulates_transcript_when_candidate_resumes() -> None:
    gate = TurnGate(canvas_quiet_seconds=0, explicit_hold_seconds=10)
    gate.on_speech_ended(1.0)
    gate.on_transcript("The API writes to a queue.", 1.1)
    gate.on_speech_started(1.15)
    gate.on_transcript("Workers consume it.", 1.3)

    assert gate.seconds_until_ready(5.0) is None
    gate.on_speech_ended(5.0)
    assert gate.consume(5.14) is None
    assert gate.consume(5.15) == "The API writes to a queue. Workers consume it."


def test_explicit_drawing_phrase_holds_floor() -> None:
    gate = TurnGate(canvas_quiet_seconds=0, explicit_hold_seconds=10)
    gate.on_speech_ended(1.0)
    gate.on_transcript("Let me draw the request flow.", 1.1)

    assert gate.consume(10.9) is None
    assert gate.consume(11.1) == "Let me draw the request flow."
