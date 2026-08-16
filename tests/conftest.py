from __future__ import annotations

from pathlib import Path

import pytest

from voice_interviewer.config import PROJECT_ROOT, Settings


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8000,
        model_root=PROJECT_ROOT / ".models",
        runtime_root=PROJECT_ROOT / ".runtime",
        stt_backend="mock",
        stt_model="base.en",
        stt_device="cpu",
        stt_compute_type="int8",
        stt_cpu_threads=2,
        silero_model_path=PROJECT_ROOT / ".models" / "silero-vad" / "silero_vad.onnx",
        sample_rate=16_000,
        vad_backend="energy",
        vad_threshold=0.5,
        vad_negative_threshold=0.35,
        vad_min_speech_ms=64,
        vad_min_silence_ms=64,
        vad_prefix_padding_ms=32,
        canvas_quiet_ms=20,
        explicit_hold_ms=50,
        llm_backend="mock",
        tts_backend="mock",
        kokoro_model_path=PROJECT_ROOT / ".models" / "kokoro" / "kokoro-v1.0.int8.onnx",
        kokoro_voices_path=PROJECT_ROOT / ".models" / "kokoro" / "voices-v1.0.bin",
        tts_voice="af_heart",
        tts_language="en-us",
        tts_speed=1.0,
        databricks_host=None,
        databricks_token=None,
        databricks_model="databricks-gpt-5-6-sol",
    )


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT
