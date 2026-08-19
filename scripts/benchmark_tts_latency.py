from __future__ import annotations

import argparse
import asyncio
import base64
import gc
import importlib.metadata
import json
import os
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from kokoro_onnx import Kokoro

from voice_interviewer.audio import float32_to_pcm16
from voice_interviewer.config import PROJECT_ROOT

MODEL_PATH = PROJECT_ROOT / ".models" / "kokoro" / "kokoro-v1.0.int8.onnx"
VOICES_PATH = PROJECT_ROOT / ".models" / "kokoro" / "voices-v1.0.bin"
VOICE = "af_heart"
LANGUAGE = "en-us"
WARMUP_TEXT = "Ready."
FIRST_CLAUSE = "That gives us a useful scale assumption."
SECOND_CLAUSE = "Walk me through the main components and the end-to-end request flow."
REPRESENTATIVE_TEXT = f"{FIRST_CLAUSE} {SECOND_CLAUSE}"


@dataclass(frozen=True, slots=True)
class SynthesisMeasurement:
    label: str
    words: int
    phonemes: int
    speed: float
    wall_seconds: float
    cpu_seconds: float
    effective_cpu_cores: float
    audio_seconds: float
    real_time_factor: float
    trim: bool


def _seconds(value: float) -> float:
    return round(value, 4)


def _measurement_summary(
    measurements: list[SynthesisMeasurement],
) -> dict[str, float | int]:
    wall_seconds = [measurement.wall_seconds for measurement in measurements]
    cpu_seconds = [measurement.cpu_seconds for measurement in measurements]
    real_time_factors = [measurement.real_time_factor for measurement in measurements]
    effective_cpu_cores = [measurement.effective_cpu_cores for measurement in measurements]
    return {
        "repetitions": len(measurements),
        "medianWallSeconds": _seconds(statistics.median(wall_seconds)),
        "minWallSeconds": _seconds(min(wall_seconds)),
        "maxWallSeconds": _seconds(max(wall_seconds)),
        "medianCpuSeconds": _seconds(statistics.median(cpu_seconds)),
        "medianEffectiveCpuCores": _seconds(statistics.median(effective_cpu_cores)),
        "medianRealTimeFactor": _seconds(statistics.median(real_time_factors)),
        "audioSeconds": measurements[0].audio_seconds,
    }


def _measure_create(
    engine: Kokoro,
    *,
    label: str,
    text: str,
    phonemes: str,
    speed: float = 1.0,
    trim: bool = True,
) -> tuple[SynthesisMeasurement, np.ndarray, int]:
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    audio, sample_rate = engine.create(
        phonemes,
        voice=VOICE,
        speed=speed,
        lang=LANGUAGE,
        is_phonemes=True,
        trim=trim,
    )
    wall_seconds = time.perf_counter() - wall_started
    cpu_seconds = time.process_time() - cpu_started
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    audio_seconds = len(samples) / int(sample_rate)
    measurement = SynthesisMeasurement(
        label=label,
        words=len(text.split()),
        phonemes=len(phonemes),
        speed=speed,
        wall_seconds=_seconds(wall_seconds),
        cpu_seconds=_seconds(cpu_seconds),
        effective_cpu_cores=_seconds(cpu_seconds / wall_seconds),
        audio_seconds=_seconds(audio_seconds),
        real_time_factor=_seconds(wall_seconds / audio_seconds),
        trim=trim,
    )
    return measurement, samples, int(sample_rate)


def _measure_repeated_create(
    engine: Kokoro,
    *,
    label: str,
    text: str,
    phonemes: str,
    repetitions: int,
    speed: float = 1.0,
    trim: bool = True,
) -> tuple[dict[str, Any], np.ndarray, int]:
    measurements: list[SynthesisMeasurement] = []
    latest_audio = np.array([], dtype=np.float32)
    sample_rate = 0
    for repetition in range(1, repetitions + 1):
        measurement, latest_audio, sample_rate = _measure_create(
            engine,
            label=f"{label}_run_{repetition}",
            text=text,
            phonemes=phonemes,
            speed=speed,
            trim=trim,
        )
        measurements.append(measurement)
    return {
        "label": label,
        "summary": _measurement_summary(measurements),
        "runs": [asdict(measurement) for measurement in measurements],
    }, latest_audio, sample_rate


def _load_default_engine() -> tuple[Kokoro, float]:
    started = time.perf_counter()
    engine = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
    return engine, _seconds(time.perf_counter() - started)


def _load_threaded_engine(
    intra_op_threads: int,
    *,
    parallel_execution: bool = False,
) -> tuple[Kokoro, float]:
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = intra_op_threads
    options.inter_op_num_threads = 1
    options.execution_mode = (
        ort.ExecutionMode.ORT_PARALLEL
        if parallel_execution
        else ort.ExecutionMode.ORT_SEQUENTIAL
    )
    started = time.perf_counter()
    session = ort.InferenceSession(
        str(MODEL_PATH),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    engine = Kokoro.from_session(session, str(VOICES_PATH))
    return engine, _seconds(time.perf_counter() - started)


async def _measure_native_stream(engine: Kokoro, text: str) -> dict[str, Any]:
    started = time.perf_counter()
    first_chunk_seconds: float | None = None
    chunks = 0
    audio_seconds = 0.0
    async for audio, sample_rate in engine.create_stream(
        text,
        voice=VOICE,
        speed=1.0,
        lang=LANGUAGE,
        trim=True,
    ):
        chunks += 1
        if first_chunk_seconds is None:
            first_chunk_seconds = time.perf_counter() - started
        audio_seconds += len(np.asarray(audio).reshape(-1)) / int(sample_rate)
    total_seconds = time.perf_counter() - started
    return {
        "chunks": chunks,
        "firstChunkSeconds": _seconds(first_chunk_seconds or total_seconds),
        "totalSeconds": _seconds(total_seconds),
        "audioSeconds": _seconds(audio_seconds),
    }


def _measure_cached_delivery(pcm_s16le: bytes, iterations: int = 100) -> dict[str, Any]:
    started = time.perf_counter()
    encoded = ""
    for _ in range(iterations):
        encoded = base64.b64encode(pcm_s16le).decode("ascii")
    base64_seconds = (time.perf_counter() - started) / iterations

    started = time.perf_counter()
    cached = b""
    for _ in range(iterations * 100):
        cached = bytes(pcm_s16le)
    memory_copy_seconds = (time.perf_counter() - started) / (iterations * 100)
    return {
        "pcmBytes": len(cached),
        "base64Characters": len(encoded),
        "meanMemoryCopySeconds": round(memory_copy_seconds, 8),
        "meanBase64Seconds": round(base64_seconds, 8),
    }


def _parse_thread_counts(value: str) -> list[int]:
    counts = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not counts or any(item < 1 for item in counts):
        raise argparse.ArgumentTypeError("thread counts must be positive integers")
    return counts


def _output_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    project_root = PROJECT_ROOT.resolve()
    if project_root not in path.parents:
        raise argparse.ArgumentTypeError(f"output must stay inside {project_root}")
    return path


def run_benchmark(
    *,
    thread_counts: list[int],
    repetitions: int,
    include_parallel: bool,
    include_native_stream: bool,
) -> dict[str, Any]:
    if not MODEL_PATH.is_file() or not VOICES_PATH.is_file():
        raise FileNotFoundError("Kokoro artifacts are missing; run the model bootstrap first")

    benchmark_started = time.perf_counter()
    engine, default_load_seconds = _load_default_engine()

    started = time.perf_counter()
    representative_phonemes = engine.tokenizer.phonemize(REPRESENTATIVE_TEXT, LANGUAGE)
    cold_phonemize_seconds = time.perf_counter() - started
    started = time.perf_counter()
    repeated_phonemes = engine.tokenizer.phonemize(REPRESENTATIVE_TEXT, LANGUAGE)
    warm_phonemize_seconds = time.perf_counter() - started
    if representative_phonemes != repeated_phonemes:
        raise RuntimeError("phonemizer returned inconsistent output")

    warmup_phonemes = engine.tokenizer.phonemize(WARMUP_TEXT, LANGUAGE)
    first_clause_phonemes = engine.tokenizer.phonemize(FIRST_CLAUSE, LANGUAGE)
    second_clause_phonemes = engine.tokenizer.phonemize(SECOND_CLAUSE, LANGUAGE)

    warmup, _, _ = _measure_create(
        engine,
        label="first_inference_warmup",
        text=WARMUP_TEXT,
        phonemes=warmup_phonemes,
    )
    whole, whole_audio, sample_rate = _measure_repeated_create(
        engine,
        label="whole_response_speed_1_0",
        text=REPRESENTATIVE_TEXT,
        phonemes=representative_phonemes,
        repetitions=repetitions,
    )
    faster, _, _ = _measure_repeated_create(
        engine,
        label="whole_response_speed_1_25",
        text=REPRESENTATIVE_TEXT,
        phonemes=representative_phonemes,
        repetitions=repetitions,
        speed=1.25,
    )
    first_clause, _, _ = _measure_repeated_create(
        engine,
        label="segmented_first_clause",
        text=FIRST_CLAUSE,
        phonemes=first_clause_phonemes,
        repetitions=repetitions,
    )
    second_clause, _, _ = _measure_repeated_create(
        engine,
        label="segmented_second_clause",
        text=SECOND_CLAUSE,
        phonemes=second_clause_phonemes,
        repetitions=repetitions,
    )

    native_stream = (
        asyncio.run(_measure_native_stream(engine, REPRESENTATIVE_TEXT))
        if include_native_stream
        else None
    )
    cached_delivery = _measure_cached_delivery(float32_to_pcm16(whole_audio))
    baseline = {
        "loadSeconds": default_load_seconds,
        "coldPhonemizeSeconds": _seconds(cold_phonemize_seconds),
        "warmPhonemizeSeconds": _seconds(warm_phonemize_seconds),
        "sampleRate": sample_rate,
        "measurements": [
            asdict(warmup),
            whole,
            faster,
            first_clause,
            second_clause,
        ],
        "segmented": {
            "timeToFirstAudioSeconds": first_clause["summary"]["medianWallSeconds"],
            "totalSynthesisSeconds": _seconds(
                first_clause["summary"]["medianWallSeconds"]
                + second_clause["summary"]["medianWallSeconds"]
            ),
            "wholeResponseSeconds": whole["summary"]["medianWallSeconds"],
        },
        "nativeStream": native_stream,
        "cachedDelivery": cached_delivery,
    }

    del engine
    gc.collect()

    thread_matrix: list[dict[str, Any]] = []
    for thread_count in thread_counts:
        threaded_engine, load_seconds = _load_threaded_engine(thread_count)
        warmup_measurement, _, _ = _measure_create(
            threaded_engine,
            label=f"threads_{thread_count}_warmup",
            text=WARMUP_TEXT,
            phonemes=warmup_phonemes,
        )
        measurement, _, _ = _measure_repeated_create(
            threaded_engine,
            label=f"threads_{thread_count}",
            text=REPRESENTATIVE_TEXT,
            phonemes=representative_phonemes,
            repetitions=repetitions,
        )
        thread_matrix.append(
            {
                "intraOpThreads": thread_count,
                "executionMode": "sequential",
                "loadSeconds": load_seconds,
                "warmup": asdict(warmup_measurement),
                "representative": measurement,
            }
        )
        del threaded_engine
        gc.collect()

    if include_parallel:
        parallel_threads = min(4, os.cpu_count() or 1)
        parallel_engine, load_seconds = _load_threaded_engine(
            parallel_threads,
            parallel_execution=True,
        )
        warmup_measurement, _, _ = _measure_create(
            parallel_engine,
            label=f"threads_{parallel_threads}_parallel_warmup",
            text=WARMUP_TEXT,
            phonemes=warmup_phonemes,
        )
        measurement, _, _ = _measure_repeated_create(
            parallel_engine,
            label=f"threads_{parallel_threads}_parallel",
            text=REPRESENTATIVE_TEXT,
            phonemes=representative_phonemes,
            repetitions=repetitions,
        )
        thread_matrix.append(
            {
                "intraOpThreads": parallel_threads,
                "executionMode": "parallel",
                "loadSeconds": load_seconds,
                "warmup": asdict(warmup_measurement),
                "representative": measurement,
            }
        )
        del parallel_engine
        gc.collect()

    return {
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logicalCpuCount": os.cpu_count(),
            "availableProviders": ort.get_available_providers(),
            "onnxruntimeVersion": importlib.metadata.version("onnxruntime"),
            "kokoroOnnxVersion": importlib.metadata.version("kokoro-onnx"),
            "model": MODEL_PATH.name,
            "voice": VOICE,
        },
        "representativeText": REPRESENTATIVE_TEXT,
        "repetitions": repetitions,
        "baseline": baseline,
        "threadMatrix": thread_matrix,
        "totalBenchmarkSeconds": _seconds(time.perf_counter() - benchmark_started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local Kokoro latency in isolation")
    parser.add_argument(
        "--thread-counts",
        type=_parse_thread_counts,
        default=_parse_thread_counts("1,2,4,8"),
        help="Comma-separated ONNX intra-op thread counts",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Measured synthesis repetitions per configuration (default: 3)",
    )
    parser.add_argument(
        "--include-parallel",
        action="store_true",
        help="Also benchmark ORT parallel execution using up to four threads",
    )
    parser.add_argument(
        "--skip-native-stream",
        action="store_true",
        help="Skip the dependency create_stream measurement",
    )
    parser.add_argument(
        "--output",
        type=_output_path,
        default=PROJECT_ROOT / ".runtime" / "tts-latency-benchmark.json",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    results = run_benchmark(
        thread_counts=args.thread_counts,
        repetitions=args.repetitions,
        include_parallel=args.include_parallel,
        include_native_stream=not args.skip_native_stream,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
