from __future__ import annotations

import argparse
import asyncio
import base64
import json
import uuid
import wave
from pathlib import Path

from websockets.asyncio.client import connect

from voice_interviewer.config import PROJECT_ROOT


def read_pcm16(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Smoke input must be mono PCM16 WAV")
        return source.readframes(source.getnframes()), source.getframerate()


async def run(base_url: str, audio_path: Path) -> None:
    audio, sample_rate = read_pcm16(audio_path)
    if sample_rate != 16_000:
        raise ValueError(f"Smoke input must be 16 kHz, got {sample_rate}")
    session_id = f"voice-smoke-{uuid.uuid4()}"
    event_types: list[str] = []
    transcript = ""
    response_text = ""
    output_bytes = 0
    output_sample_rate = 0
    async with connect(f"{base_url.rstrip('/')}/ws/interview/{session_id}", proxy=None) as socket:
        ready = json.loads(await socket.recv())
        if ready.get("type") != "session.ready":
            raise RuntimeError(f"Unexpected first event: {ready}")
        ready_payload = ready.get("payload", {})
        expected_backends = {
            "sttBackend": "faster-whisper",
            "vadBackend": "silero",
            "ttsBackend": "kokoro",
        }
        if any(ready_payload.get(key) != value for key, value in expected_backends.items()):
            raise RuntimeError(f"Real local backends are not active: {ready_payload}")
        await socket.send(
            json.dumps(
                {
                    "type": "session.configure",
                    "payload": {
                        "problem": "Design a resilient public API",
                        "glossary": ["load balancer", "database", "cache"],
                    },
                }
            )
        )
        configured = json.loads(await socket.recv())
        if configured.get("type") != "session.configured":
            raise RuntimeError(f"Unexpected configuration event: {configured}")
        frame_bytes = 512 * 2
        for offset in range(0, len(audio), frame_bytes):
            await socket.send(audio[offset : offset + frame_bytes])
            if offset % (frame_bytes * 32) == 0:
                await asyncio.sleep(0)
        await socket.send(json.dumps({"type": "audio.flush", "payload": {}}))

        async with asyncio.timeout(120):
            while True:
                event = json.loads(await socket.recv())
                event_type = str(event.get("type", ""))
                event_types.append(event_type)
                payload = event.get("payload", {})
                if event_type == "error":
                    raise RuntimeError(f"Pipeline error: {payload}")
                if event_type == "candidate.transcript.final":
                    transcript = str(payload.get("text", ""))
                elif event_type == "assistant.text.final":
                    response_text = str(payload.get("text", ""))
                elif event_type == "assistant.audio.chunk":
                    output_bytes = len(base64.b64decode(str(payload.get("audio", ""))))
                    output_sample_rate = int(payload.get("sampleRate", 0))
                elif event_type == "assistant.response.completed":
                    break

    if not transcript or not response_text or output_bytes <= 1_000 or output_sample_rate != 24_000:
        raise RuntimeError("Voice turn did not produce real STT and Kokoro speech")
    print(
        json.dumps(
            {
                "transcript": transcript,
                "response": response_text,
                "audioBytes": output_bytes,
                "audioSampleRate": output_sample_rate,
                "events": event_types,
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test one complete local voice turn")
    parser.add_argument("url", nargs="?", default="ws://127.0.0.1:8000")
    parser.add_argument(
        "--audio",
        type=Path,
        default=PROJECT_ROOT / ".cache" / "test-assets" / "jfk.wav",
    )
    args = parser.parse_args()
    asyncio.run(run(args.url, args.audio.resolve()))


if __name__ == "__main__":
    main()
