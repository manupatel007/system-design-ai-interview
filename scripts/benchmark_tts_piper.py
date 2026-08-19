from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from piper import PiperVoice

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / ".models" / "piper" / "en_US-lessac-medium.onnx"
CONFIG_PATH = PROJECT_ROOT / ".models" / "piper" / "en_US-lessac-medium.onnx.json"
WARMUP_TEXT = "Ready."
REPRESENTATIVE_TEXT = (
    "That gives us a useful scale assumption. "
    "Walk me through the main components and the end-to-end request flow."
)


@dataclass(frozen=True, slots=True)
class Measurement:
    wall_seconds: float
    first_chunk_seconds: float
    audio_seconds: float
    real_time_factor: float
    chunks: int


def _seconds(value: float) -> float:
    return round(value, 5)


def _measure(voice: PiperVoice, text: str) -> Measurement:
    started = time.perf_counter()
    first_chunk_seconds: float | None = None
    chunks = 0
    audio_seconds = 0.0
    for chunk in voice.synthesize(text):
        chunks += 1
        if first_chunk_seconds is None:
            first_chunk_seconds = time.perf_counter() - started
        samples = np.asarray(chunk.audio_float_array).reshape(-1)
        audio_seconds += len(samples) / chunk.sample_rate
    wall_seconds = time.perf_counter() - started
    if not chunks or not audio_seconds or first_chunk_seconds is None:
        raise RuntimeError("Piper returned no audio")
    return Measurement(
        wall_seconds=_seconds(wall_seconds),
        first_chunk_seconds=_seconds(first_chunk_seconds),
        audio_seconds=_seconds(audio_seconds),
        real_time_factor=_seconds(wall_seconds / audio_seconds),
        chunks=chunks,
    )


def _summary(measurements: list[Measurement]) -> dict[str, float | int]:
    wall_seconds = [measurement.wall_seconds for measurement in measurements]
    first_chunk_seconds = [
        measurement.first_chunk_seconds for measurement in measurements
    ]
    audio_seconds = [measurement.audio_seconds for measurement in measurements]
    real_time_factors = [measurement.real_time_factor for measurement in measurements]
    return {
        "repetitions": len(measurements),
        "medianWallSeconds": _seconds(statistics.median(wall_seconds)),
        "minWallSeconds": _seconds(min(wall_seconds)),
        "maxWallSeconds": _seconds(max(wall_seconds)),
        "medianFirstChunkSeconds": _seconds(statistics.median(first_chunk_seconds)),
        "medianAudioSeconds": _seconds(statistics.median(audio_seconds)),
        "medianRealTimeFactor": _seconds(statistics.median(real_time_factors)),
        "chunks": measurements[0].chunks,
    }


def _output_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    project_root = PROJECT_ROOT.resolve()
    if project_root not in path.parents:
        raise argparse.ArgumentTypeError(f"output must stay inside {project_root}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark a CPU-oriented Piper voice against the Kokoro test text"
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument(
        "--output",
        type=_output_path,
        default=PROJECT_ROOT / ".runtime" / "tts-piper-benchmark.json",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if not MODEL_PATH.is_file() or not CONFIG_PATH.is_file():
        raise FileNotFoundError(
            "Piper voice is missing; download en_US-lessac-medium into .models/piper"
        )

    benchmark_started = time.perf_counter()
    load_started = time.perf_counter()
    voice = PiperVoice.load(MODEL_PATH, CONFIG_PATH)
    load_seconds = time.perf_counter() - load_started
    warmup = _measure(voice, WARMUP_TEXT)
    measurements = [
        _measure(voice, REPRESENTATIVE_TEXT) for _ in range(args.repetitions)
    ]
    results = {
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logicalCpuCount": os.cpu_count(),
            "onnxruntimeVersion": ort.__version__,
            "availableProviders": ort.get_available_providers(),
            "model": MODEL_PATH.name,
            "modelBytes": MODEL_PATH.stat().st_size,
        },
        "representativeText": REPRESENTATIVE_TEXT,
        "loadSeconds": _seconds(load_seconds),
        "warmup": asdict(warmup),
        "representative": {
            "summary": _summary(measurements),
            "runs": [asdict(measurement) for measurement in measurements],
        },
        "totalBenchmarkSeconds": _seconds(
            time.perf_counter() - benchmark_started
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
