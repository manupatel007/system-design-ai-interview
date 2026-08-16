from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace

import uvicorn

from voice_interviewer.config import Settings
from voice_interviewer.server import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local voice-interviewer pipeline")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Run the local web and WebSocket server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument(
        "--mock",
        action="store_true",
        help="Use energy VAD, mock STT, mock LLM, and mock TTS",
    )
    subparsers.add_parser("doctor", help="Print sanitized local readiness information")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    command = args.command or "serve"
    settings = Settings.from_env()
    settings.prepare_directories()
    if command == "doctor":
        print(
            json.dumps(
                {
                    "projectRoot": str(settings.model_root.parent),
                    "modelRoot": str(settings.model_root),
                    "runtimeRoot": str(settings.runtime_root),
                    "sttBackend": settings.stt_backend,
                    "sttModel": settings.stt_model,
                    "sileroReady": settings.silero_model_path.is_file(),
                    "ttsBackend": settings.tts_backend,
                    "ttsVoice": settings.tts_voice,
                    "kokoroReady": settings.kokoro_model_path.is_file()
                    and settings.kokoro_voices_path.is_file(),
                    "databricksConfigured": bool(
                        settings.databricks_host and settings.databricks_token
                    ),
                },
                indent=2,
            )
        )
        return
    if getattr(args, "mock", False):
        settings = replace(
            settings,
            stt_backend="mock",
            vad_backend="energy",
            llm_backend="mock",
            tts_backend="mock",
        )
    host = getattr(args, "host", None) or settings.host
    port = getattr(args, "port", None) or settings.port
    os.environ.setdefault("HF_HOME", str(settings.model_root / ".huggingface"))
    uvicorn.run(create_app(settings), host=host, port=port)
