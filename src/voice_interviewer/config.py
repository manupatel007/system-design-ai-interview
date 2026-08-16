from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_path(environment_key: str, default: str) -> Path:
    configured = Path(os.getenv(environment_key, PROJECT_ROOT / default)).expanduser().resolve()
    project_root = PROJECT_ROOT.resolve()
    if configured != project_root and project_root not in configured.parents:
        raise ValueError(f"{environment_key} must stay inside {project_root}")
    return configured


def _integer(environment_key: str, default: int) -> int:
    return int(os.getenv(environment_key, str(default)))


def _floating(environment_key: str, default: float) -> float:
    return float(os.getenv(environment_key, str(default)))


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    model_root: Path
    runtime_root: Path
    stt_backend: str
    stt_model: str
    stt_device: str
    stt_compute_type: str
    stt_cpu_threads: int
    silero_model_path: Path
    sample_rate: int
    vad_backend: str
    vad_threshold: float
    vad_negative_threshold: float
    vad_min_speech_ms: int
    vad_min_silence_ms: int
    vad_prefix_padding_ms: int
    canvas_quiet_ms: int
    explicit_hold_ms: int
    llm_backend: str
    tts_backend: str
    kokoro_model_path: Path
    kokoro_voices_path: Path
    tts_voice: str
    tts_language: str
    tts_speed: float
    databricks_host: str | None
    databricks_token: str | None
    databricks_model: str

    @classmethod
    def from_env(cls) -> Settings:
        model_root = _project_path("VOICE_MODEL_ROOT", ".models")
        runtime_root = _project_path("VOICE_RUNTIME_ROOT", ".runtime")
        return cls(
            host=os.getenv("VOICE_HOST", "127.0.0.1"),
            port=_integer("VOICE_PORT", 8000),
            model_root=model_root,
            runtime_root=runtime_root,
            stt_backend=os.getenv("VOICE_STT_BACKEND", "faster-whisper"),
            stt_model=os.getenv("VOICE_STT_MODEL", "base.en"),
            stt_device=os.getenv("VOICE_STT_DEVICE", "cpu"),
            stt_compute_type=os.getenv("VOICE_STT_COMPUTE_TYPE", "int8"),
            stt_cpu_threads=_integer("VOICE_STT_CPU_THREADS", 4),
            silero_model_path=model_root / "silero-vad" / "silero_vad.onnx",
            sample_rate=_integer("VOICE_SAMPLE_RATE", 16_000),
            vad_backend=os.getenv("VOICE_VAD_BACKEND", "silero"),
            vad_threshold=_floating("VOICE_VAD_THRESHOLD", 0.5),
            vad_negative_threshold=_floating("VOICE_VAD_NEGATIVE_THRESHOLD", 0.35),
            vad_min_speech_ms=_integer("VOICE_VAD_MIN_SPEECH_MS", 96),
            vad_min_silence_ms=_integer("VOICE_VAD_MIN_SILENCE_MS", 1_200),
            vad_prefix_padding_ms=_integer("VOICE_VAD_PREFIX_PADDING_MS", 256),
            canvas_quiet_ms=_integer("VOICE_CANVAS_QUIET_MS", 1_500),
            explicit_hold_ms=_integer("VOICE_EXPLICIT_HOLD_MS", 10_000),
            llm_backend=os.getenv("VOICE_LLM_BACKEND", "mock"),
            tts_backend=os.getenv("VOICE_TTS_BACKEND", "kokoro"),
            kokoro_model_path=_project_path(
                "VOICE_TTS_MODEL_PATH", ".models/kokoro/kokoro-v1.0.int8.onnx"
            ),
            kokoro_voices_path=_project_path(
                "VOICE_TTS_VOICES_PATH", ".models/kokoro/voices-v1.0.bin"
            ),
            tts_voice=os.getenv("VOICE_TTS_VOICE", "af_heart"),
            tts_language=os.getenv("VOICE_TTS_LANGUAGE", "en-us"),
            tts_speed=_floating("VOICE_TTS_SPEED", 1.0),
            databricks_host=os.getenv("DATABRICKS_HOST") or None,
            databricks_token=os.getenv("DATABRICKS_TOKEN") or None,
            databricks_model=os.getenv(
                "DATABRICKS_MODEL", "databricks-gpt-5-6-sol"
            ),
        )

    def prepare_directories(self) -> None:
        self.model_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
