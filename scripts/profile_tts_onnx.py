from __future__ import annotations

import argparse
import json
import os
import platform
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import onnxruntime as ort
from kokoro_onnx import Kokoro

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / ".models" / "kokoro" / "kokoro-v1.0.int8.onnx"
VOICES_PATH = PROJECT_ROOT / ".models" / "kokoro" / "voices-v1.0.bin"
VOICE = "af_heart"
LANGUAGE = "en-us"
REPRESENTATIVE_TEXT = (
    "That gives us a useful scale assumption. "
    "Walk me through the main components and the end-to-end request flow."
)


def _seconds(value: float) -> float:
    return round(value, 4)


def _output_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    project_root = PROJECT_ROOT.resolve()
    if project_root not in path.parents:
        raise argparse.ArgumentTypeError(f"output must stay inside {project_root}")
    return path


def _aggregate(
    events: list[dict[str, Any]],
    *,
    name_key: str,
    total_duration_microseconds: int,
    limit: int,
) -> list[dict[str, Any]]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for event in events:
        if name_key == "op_name":
            name = event.get("args", {}).get("op_name", "unknown")
        else:
            name = event.get("name", "unknown").removesuffix("_kernel_time")
        totals[name][0] += int(event.get("dur", 0))
        totals[name][1] += 1
    ranked = sorted(totals.items(), key=lambda item: item[1][0], reverse=True)
    return [
        {
            "name": name,
            "durationMilliseconds": round(duration / 1000, 2),
            "percentOfNodeTime": round(
                100 * duration / total_duration_microseconds,
                2,
            ),
            "calls": calls,
        }
        for name, (duration, calls) in ranked[:limit]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile Kokoro ONNX operators for the representative interview response"
    )
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument(
        "--output",
        type=_output_path,
        default=PROJECT_ROOT / ".runtime" / "tts-onnx-profile-summary.json",
    )
    args = parser.parse_args()
    if args.threads < 1 or args.runs < 1 or args.top < 1:
        parser.error("--threads, --runs, and --top must be at least 1")
    if not MODEL_PATH.is_file() or not VOICES_PATH.is_file():
        raise FileNotFoundError("Kokoro artifacts are missing; run the model bootstrap first")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    options = ort.SessionOptions()
    options.enable_profiling = True
    options.profile_file_prefix = str(args.output.parent / "kokoro-ort-profile")
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(MODEL_PATH),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    engine = Kokoro.from_session(session, str(VOICES_PATH))
    phonemes = engine.tokenizer.phonemize(REPRESENTATIVE_TEXT, LANGUAGE)
    run_wall_seconds: list[float] = []
    for _ in range(args.runs):
        started = time.perf_counter()
        engine.create(
            phonemes,
            voice=VOICE,
            lang=LANGUAGE,
            is_phonemes=True,
            trim=True,
        )
        run_wall_seconds.append(_seconds(time.perf_counter() - started))

    raw_profile_path = Path(session.end_profiling())
    profile_events = json.loads(raw_profile_path.read_text(encoding="utf-8"))
    model_runs = [
        event
        for event in profile_events
        if event.get("cat") == "Session" and event.get("name") == "model_run"
    ]
    if not model_runs:
        raise RuntimeError("ONNX Runtime profile did not contain a model_run event")
    last_model_run = model_runs[-1]
    run_started = int(last_model_run["ts"])
    run_ended = run_started + int(last_model_run["dur"])
    node_events = [
        event
        for event in profile_events
        if event.get("cat") == "Node"
        and run_started <= int(event.get("ts", 0)) < run_ended
    ]
    total_node_microseconds = sum(int(event.get("dur", 0)) for event in node_events)
    if not total_node_microseconds:
        raise RuntimeError("ONNX Runtime profile did not contain timed node events")

    results = {
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logicalCpuCount": os.cpu_count(),
            "onnxruntimeVersion": ort.__version__,
            "model": MODEL_PATH.name,
            "threads": args.threads,
        },
        "representativeText": REPRESENTATIVE_TEXT,
        "runWallSeconds": run_wall_seconds,
        "profiledRunMilliseconds": round(int(last_model_run["dur"]) / 1000, 2),
        "nodeMilliseconds": round(total_node_microseconds / 1000, 2),
        "nodeEvents": len(node_events),
        "topOperations": _aggregate(
            node_events,
            name_key="op_name",
            total_duration_microseconds=total_node_microseconds,
            limit=args.top,
        ),
        "topNodes": _aggregate(
            node_events,
            name_key="name",
            total_duration_microseconds=total_node_microseconds,
            limit=args.top,
        ),
        "rawProfile": str(raw_profile_path.relative_to(PROJECT_ROOT)),
    }
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
