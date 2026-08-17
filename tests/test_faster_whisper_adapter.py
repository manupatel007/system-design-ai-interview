from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from voice_interviewer.config import PROJECT_ROOT
from voice_interviewer.stt.faster_whisper import FasterWhisperSTT


@dataclass
class FakeSegment:
    text: str
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    start: float = 0.0
    end: float = 1.0


class FakeInfo:
    language = "en"


class FakeWhisperModel:
    def __init__(self, segments: list[FakeSegment]) -> None:
        self.segments = segments
        self.options: dict[str, object] = {}

    def transcribe(self, _audio, **options):
        self.options = options
        return iter(self.segments), FakeInfo()


def _transcriber(segments: list[FakeSegment]) -> tuple[FasterWhisperSTT, FakeWhisperModel]:
    transcriber = FasterWhisperSTT(model_name="base.en", model_root=PROJECT_ROOT / ".models")
    model = FakeWhisperModel(segments)
    transcriber._model = model
    return transcriber, model


def test_glossary_is_sent_as_hotwords_not_initial_prompt() -> None:
    transcriber, model = _transcriber(
        [FakeSegment("Redis is the cache.", -0.2, 0.02, 1.1)],
    )

    result = transcriber._transcribe_sync(
        np.zeros(16_000, dtype=np.float32),
        "Kafka, Redis, PostgreSQL",
    )

    assert model.options["hotwords"] == "Kafka, Redis, PostgreSQL"
    assert "initial_prompt" not in model.options
    assert result.text == "Redis is the cache."
    assert result.segments[0].no_speech_probability == pytest.approx(0.02)
    assert result.segments[0].compression_ratio == pytest.approx(1.1)


@pytest.mark.parametrize(
    ("segment", "duration_seconds"),
    [
        (FakeSegment("System design interview.", -0.82, 0.63, 0.75), 0.35),
        (FakeSegment("S-S-S-S-S-S-S-S", -0.06, 0.30, 14.1), 0.60),
        (FakeSegment("and the other one", -1.87, 0.54, 0.75), 0.35),
        (FakeSegment("and", -0.90, 0.35, 0.27), 0.60),
    ],
)
def test_unreliable_short_decodes_are_rejected(segment, duration_seconds) -> None:
    transcriber, _ = _transcriber([segment])
    audio = np.zeros(round(duration_seconds * 16_000), dtype=np.float32)

    result = transcriber._transcribe_sync(audio, "Kafka, Redis")

    assert result.text == ""
    assert result.segments == ()


def test_confident_short_answer_is_retained() -> None:
    transcriber, _ = _transcriber(
        [FakeSegment("Yes.", -0.22, 0.08, 0.4, end=0.6)],
    )

    result = transcriber._transcribe_sync(
        np.zeros(round(0.6 * 16_000), dtype=np.float32),
        "Kafka, Redis",
    )

    assert result.text == "Yes."
