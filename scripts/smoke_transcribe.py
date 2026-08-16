from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from faster_whisper.audio import decode_audio

from voice_interviewer.config import PROJECT_ROOT, Settings
from voice_interviewer.stt.faster_whisper import FasterWhisperSTT


async def run(audio_path: Path) -> None:
    settings = Settings.from_env()
    transcriber = FasterWhisperSTT(
        model_name=settings.stt_model,
        model_root=settings.model_root,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        cpu_threads=settings.stt_cpu_threads,
    )
    audio = decode_audio(str(audio_path), sampling_rate=settings.sample_rate)
    transcript = await transcriber.transcribe(
        audio,
        prompt="System design interview. Expected technical terms: database, cache, queue.",
    )
    print(transcript.text)
    if not transcript.text:
        raise SystemExit("Smoke transcription returned no text")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run base.en against a local WAV sample")
    parser.add_argument(
        "audio",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / ".cache" / "test-assets" / "jfk.wav",
    )
    args = parser.parse_args()
    asyncio.run(run(args.audio.resolve()))


if __name__ == "__main__":
    main()
