from __future__ import annotations

import numpy as np
import pytest

from voice_interviewer.config import PROJECT_ROOT
from voice_interviewer.errors import ConfigurationError, ModelNotReadyError
from voice_interviewer.tts.kokoro import KokoroTTS


class FakeKokoroEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, text: str, **options: object) -> tuple[np.ndarray, int]:
        self.calls.append({"text": text, **options})
        return np.array([-0.5, 0.0, 0.5], dtype=np.float32), 24_000


@pytest.mark.asyncio
async def test_kokoro_tts_returns_pcm_audio() -> None:
    engine = FakeKokoroEngine()
    tts = KokoroTTS(
        model_path=PROJECT_ROOT / "model.onnx",
        voices_path=PROJECT_ROOT / "voices.bin",
        voice="af_heart",
        language="en-us",
        speed=1.1,
    )
    tts._engine = engine

    output = await tts.synthesize("  Ask about failover.  ")

    assert output.sample_rate == 24_000
    assert output.channels == 1
    assert np.frombuffer(output.pcm_s16le, dtype="<i2").tolist() == [-16383, 0, 16383]
    assert engine.calls == [
        {
            "text": "Ask about failover.",
            "voice": "af_heart",
            "speed": 1.1,
            "lang": "en-us",
        }
    ]


@pytest.mark.asyncio
async def test_kokoro_tts_reports_missing_model_files() -> None:
    tts = KokoroTTS(
        model_path=PROJECT_ROOT / ".missing-kokoro-model.onnx",
        voices_path=PROJECT_ROOT / ".missing-kokoro-voices.bin",
    )

    with pytest.raises(ModelNotReadyError, match="download_models.py --kokoro"):
        await tts.load()


def test_kokoro_tts_rejects_invalid_speed() -> None:
    with pytest.raises(ConfigurationError, match="speed"):
        KokoroTTS(
            model_path=PROJECT_ROOT / "model.onnx",
            voices_path=PROJECT_ROOT / "voices.bin",
            speed=2.5,
        )
