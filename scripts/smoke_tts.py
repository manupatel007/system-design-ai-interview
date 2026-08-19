from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

from voice_interviewer.adapters import create_tts
from voice_interviewer.config import PROJECT_ROOT, Settings


async def synthesize(text: str, destination: Path) -> dict[str, object]:
    settings = Settings.from_env()
    settings.prepare_directories()
    tts = create_tts(settings)
    started = time.perf_counter()
    output = await tts.synthesize(text)
    elapsed = time.perf_counter() - started
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as target:
        target.setnchannels(output.channels)
        target.setsampwidth(2)
        target.setframerate(output.sample_rate)
        target.writeframes(output.pcm_s16le)
    duration = len(output.pcm_s16le) / (2 * output.channels * output.sample_rate)
    return {
        "output": str(destination.relative_to(PROJECT_ROOT)),
        "backend": settings.tts_backend,
        "model": settings.tts_model,
        "sampleRate": output.sample_rate,
        "audioSeconds": round(duration, 2),
        "synthesisSeconds": round(elapsed, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize a local TTS WAV")
    parser.add_argument(
        "--text",
        default="How would your design handle a sudden database failure?",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".runtime" / "tts-smoke.wav",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(synthesize(args.text, args.output.resolve())), indent=2))


if __name__ == "__main__":
    main()
