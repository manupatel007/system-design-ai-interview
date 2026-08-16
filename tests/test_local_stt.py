from __future__ import annotations

import pytest
from faster_whisper.audio import decode_audio

from voice_interviewer.stt.faster_whisper import FasterWhisperSTT


@pytest.mark.asyncio
async def test_downloaded_base_en_transcribes_sample(project_root) -> None:
    model_root = project_root / ".models"
    sample = project_root / ".cache" / "test-assets" / "jfk.wav"
    if not (model_root / "faster-whisper-base.en").is_dir() or not sample.is_file():
        pytest.skip("Run scripts/download_models.py --all")
    transcriber = FasterWhisperSTT(
        model_name="base.en",
        model_root=model_root,
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
    )
    audio = decode_audio(str(sample), sampling_rate=16_000)

    result = await transcriber.transcribe(audio)

    assert "fellow americans" in result.text.lower()
