from __future__ import annotations

from dataclasses import dataclass

import pytest

from voice_interviewer.config import PROJECT_ROOT
from voice_interviewer.errors import ConfigurationError, ModelNotReadyError
from voice_interviewer.tts.piper import PiperTTS


@dataclass
class FakePiperChunk:
    audio_int16_bytes: bytes
    sample_rate: int = 22_050
    sample_width: int = 2
    sample_channels: int = 1


class FakePiperEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def synthesize(self, text: str, *, syn_config):
        self.calls.append({"text": text, "length_scale": syn_config.length_scale})
        yield FakePiperChunk(b"\x01\x00\x02\x00")
        yield FakePiperChunk(b"\x03\x00\x04\x00")


@pytest.mark.asyncio
async def test_piper_tts_streams_sentence_chunks() -> None:
    engine = FakePiperEngine()
    tts = PiperTTS(
        model_path=PROJECT_ROOT / "voice.onnx",
        config_path=PROJECT_ROOT / "voice.onnx.json",
        speed=1.25,
    )
    tts._engine = engine

    chunks = [chunk async for chunk in tts.synthesize_stream("  First. Second.  ")]

    assert [chunk.pcm_s16le for chunk in chunks] == [
        b"\x01\x00\x02\x00",
        b"\x03\x00\x04\x00",
    ]
    assert all(chunk.sample_rate == 22_050 for chunk in chunks)
    assert engine.calls == [{"text": "First. Second.", "length_scale": 0.8}]


@pytest.mark.asyncio
async def test_piper_tts_combines_chunks_for_legacy_callers() -> None:
    tts = PiperTTS(
        model_path=PROJECT_ROOT / "voice.onnx",
        config_path=PROJECT_ROOT / "voice.onnx.json",
    )
    tts._engine = FakePiperEngine()

    output = await tts.synthesize("Ask about failover.")

    assert output.pcm_s16le == b"\x01\x00\x02\x00\x03\x00\x04\x00"
    assert output.sample_rate == 22_050
    assert output.channels == 1


@pytest.mark.asyncio
async def test_piper_tts_reports_missing_model_files() -> None:
    tts = PiperTTS(
        model_path=PROJECT_ROOT / ".missing-piper-model.onnx",
        config_path=PROJECT_ROOT / ".missing-piper-config.onnx.json",
    )

    with pytest.raises(ModelNotReadyError, match="download_models.py --piper"):
        await tts.load()


def test_piper_tts_rejects_invalid_speed() -> None:
    with pytest.raises(ConfigurationError, match="speed"):
        PiperTTS(
            model_path=PROJECT_ROOT / "voice.onnx",
            config_path=PROJECT_ROOT / "voice.onnx.json",
            speed=2.5,
        )
