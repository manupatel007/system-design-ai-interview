from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import openvino as ov
from kokoro_onnx import Kokoro

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / ".models" / "kokoro" / "kokoro-v1.0.int8.onnx"
VOICES_PATH = PROJECT_ROOT / ".models" / "kokoro" / "voices-v1.0.bin"
VOICE = "af_heart"
LANGUAGE = "en-us"
WARMUP_TEXT = "Ready."
FIRST_CLAUSE = "That gives us a useful scale assumption."
SECOND_CLAUSE = (
    "Walk me through the main components and the end-to-end request flow."
)
REPRESENTATIVE_TEXT = f"{FIRST_CLAUSE} {SECOND_CLAUSE}"


@dataclass(frozen=True, slots=True)
class Measurement:
    wall_seconds: float
    audio_seconds: float
    real_time_factor: float


@dataclass(frozen=True, slots=True)
class _SessionInput:
    name: str


class OpenVINOSessionAdapter:
    def __init__(self, model_path: Path, device: str, cpu_threads: int) -> None:
        self._model_path = str(model_path)
        self._core = ov.Core()
        read_started = time.perf_counter()
        model = self._core.read_model(self._model_path)
        self.read_seconds = time.perf_counter() - read_started
        compile_started = time.perf_counter()
        compile_config = {"PERFORMANCE_HINT": "LATENCY"}
        if device == "CPU":
            compile_config.update(
                {
                    "INFERENCE_NUM_THREADS": str(cpu_threads),
                    "NUM_STREAMS": "1",
                }
            )
        self._compiled_model = self._core.compile_model(model, device, compile_config)
        self.compile_seconds = time.perf_counter() - compile_started
        self.full_device_name = self._core.get_property(device, "FULL_DEVICE_NAME")
        self._inputs = [
            _SessionInput(input_port.any_name) for input_port in self._compiled_model.inputs
        ]

    def get_inputs(self) -> list[_SessionInput]:
        return self._inputs

    def run(
        self,
        output_names: None,
        inputs: dict[str, Any],
    ) -> list[np.ndarray]:
        del output_names
        normalized_inputs = {name: np.asarray(value) for name, value in inputs.items()}
        result = self._compiled_model(normalized_inputs)
        return [
            np.asarray(result[output]).reshape(-1)
            for output in self._compiled_model.outputs
        ]


def _seconds(value: float) -> float:
    return round(value, 4)


def _measure(engine: Kokoro, phonemes: str) -> Measurement:
    started = time.perf_counter()
    audio, sample_rate = engine.create(
        phonemes,
        voice=VOICE,
        speed=1.0,
        lang=LANGUAGE,
        is_phonemes=True,
        trim=True,
    )
    wall_seconds = time.perf_counter() - started
    audio_seconds = len(np.asarray(audio).reshape(-1)) / int(sample_rate)
    return Measurement(
        wall_seconds=_seconds(wall_seconds),
        audio_seconds=_seconds(audio_seconds),
        real_time_factor=_seconds(wall_seconds / audio_seconds),
    )


def _summary(measurements: list[Measurement]) -> dict[str, float | int]:
    wall_seconds = [measurement.wall_seconds for measurement in measurements]
    real_time_factors = [measurement.real_time_factor for measurement in measurements]
    return {
        "repetitions": len(measurements),
        "medianWallSeconds": _seconds(statistics.median(wall_seconds)),
        "minWallSeconds": _seconds(min(wall_seconds)),
        "maxWallSeconds": _seconds(max(wall_seconds)),
        "audioSeconds": measurements[0].audio_seconds,
        "medianRealTimeFactor": _seconds(statistics.median(real_time_factors)),
    }


def _benchmark_device(
    device: str,
    repetitions: int,
    cpu_threads: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    session = OpenVINOSessionAdapter(MODEL_PATH, device, cpu_threads)
    engine = Kokoro.from_session(session, str(VOICES_PATH))
    load_seconds = time.perf_counter() - started
    representative_phonemes = engine.tokenizer.phonemize(REPRESENTATIVE_TEXT, LANGUAGE)
    first_clause_phonemes = engine.tokenizer.phonemize(FIRST_CLAUSE, LANGUAGE)
    second_clause_phonemes = engine.tokenizer.phonemize(SECOND_CLAUSE, LANGUAGE)
    warmup_phonemes = engine.tokenizer.phonemize(WARMUP_TEXT, LANGUAGE)
    warmup = _measure(engine, warmup_phonemes)
    measurements = [
        _measure(engine, representative_phonemes) for _ in range(repetitions)
    ]
    first_clause_measurements = [
        _measure(engine, first_clause_phonemes) for _ in range(repetitions)
    ]
    second_clause_measurements = [
        _measure(engine, second_clause_phonemes) for _ in range(repetitions)
    ]
    first_clause_summary = _summary(first_clause_measurements)
    second_clause_summary = _summary(second_clause_measurements)
    return {
        "device": device,
        "fullDeviceName": session.full_device_name,
        "modelReadSeconds": _seconds(session.read_seconds),
        "modelCompileSeconds": _seconds(session.compile_seconds),
        "totalLoadSeconds": _seconds(load_seconds),
        "warmup": asdict(warmup),
        "representative": {
            "summary": _summary(measurements),
            "runs": [asdict(measurement) for measurement in measurements],
        },
        "segmented": {
            "timeToFirstAudioSeconds": first_clause_summary["medianWallSeconds"],
            "totalSynthesisSeconds": _seconds(
                first_clause_summary["medianWallSeconds"]
                + second_clause_summary["medianWallSeconds"]
            ),
            "firstClause": {
                "summary": first_clause_summary,
                "runs": [
                    asdict(measurement)
                    for measurement in first_clause_measurements
                ],
            },
            "secondClause": {
                "summary": second_clause_summary,
                "runs": [
                    asdict(measurement)
                    for measurement in second_clause_measurements
                ],
            },
        },
    }


def _output_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    project_root = PROJECT_ROOT.resolve()
    if project_root not in path.parents:
        raise argparse.ArgumentTypeError(f"output must stay inside {project_root}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Kokoro through native OpenVINO on Intel CPU/GPU"
    )
    parser.add_argument(
        "--devices",
        default="CPU,GPU",
        help="Comma-separated OpenVINO devices (default: CPU,GPU)",
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument(
        "--output",
        type=_output_path,
        default=PROJECT_ROOT / ".runtime" / "tts-openvino-native-benchmark.json",
    )
    args = parser.parse_args()
    devices = [device.strip().upper() for device in args.devices.split(",") if device.strip()]
    if not devices:
        parser.error("--devices must contain at least one device")
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.cpu_threads < 1:
        parser.error("--cpu-threads must be at least 1")
    if not MODEL_PATH.is_file() or not VOICES_PATH.is_file():
        raise FileNotFoundError("Kokoro artifacts are missing; run the model bootstrap first")

    benchmark_started = time.perf_counter()
    core = ov.Core()
    results: dict[str, Any] = {
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logicalCpuCount": os.cpu_count(),
            "openvinoVersion": ov.__version__,
            "availableDevices": core.available_devices,
            "model": MODEL_PATH.name,
            "voice": VOICE,
        },
        "representativeText": REPRESENTATIVE_TEXT,
        "devices": [],
    }
    for device in devices:
        try:
            results["devices"].append(
                _benchmark_device(device, args.repetitions, args.cpu_threads)
            )
        except Exception as error:
            results["devices"].append(
                {
                    "device": device,
                    "errorType": type(error).__name__,
                    "error": str(error),
                }
            )
        gc.collect()
    results["totalBenchmarkSeconds"] = _seconds(
        time.perf_counter() - benchmark_started
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
