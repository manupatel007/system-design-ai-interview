from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from voice_interviewer.adapters import create_llm, create_stt, create_tts
from voice_interviewer.config import Settings
from voice_interviewer.errors import ConfigurationError
from voice_interviewer.models import InterviewLanguageModel, SpeechToText, TextToSpeech
from voice_interviewer.pipeline import InterviewSessionPipeline
from voice_interviewer.vad.energy import EnergyVad
from voice_interviewer.vad.silero import SileroOnnxVad

STATIC_ROOT = Path(__file__).resolve().parent / "static"


@dataclass(slots=True)
class ApplicationServices:
    settings: Settings
    stt: SpeechToText
    llm: InterviewLanguageModel
    tts: TextToSpeech


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    active_settings.prepare_directories()
    services = ApplicationServices(
        settings=active_settings,
        stt=create_stt(active_settings),
        llm=create_llm(active_settings),
        tts=create_tts(active_settings),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        load_stt = getattr(services.stt, "load", None)
        if load_stt is not None and getattr(services.stt, "ready", True):
            await load_stt()
        load_tts = getattr(services.tts, "load", None)
        if load_tts is not None and getattr(services.tts, "ready", False):
            await load_tts()
        yield

    app = FastAPI(title="Voice Interviewer", version="0.1.0", lifespan=lifespan)
    app.state.services = services
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "backends": {
                "stt": active_settings.stt_backend,
                "vad": active_settings.vad_backend,
                "llm": active_settings.llm_backend,
                "tts": active_settings.tts_backend,
            },
            "models": {
                "stt": active_settings.stt_model,
                "sttReady": (
                    active_settings.stt_backend == "mock"
                    or bool(getattr(services.stt, "ready", False))
                ),
                "sttLoaded": (
                    active_settings.stt_backend == "mock"
                    or bool(getattr(services.stt, "loaded", False))
                ),
                "sileroReady": active_settings.silero_model_path.is_file(),
                "ttsModel": active_settings.tts_model,
                "ttsReady": active_settings.tts_ready,
                "ttsVoice": (
                    active_settings.tts_voice
                    if active_settings.tts_backend == "kokoro"
                    else None
                ),
                "kokoroReady": active_settings.kokoro_model_path.is_file()
                and active_settings.kokoro_voices_path.is_file(),
                "piperReady": active_settings.piper_model_path.is_file()
                and active_settings.piper_config_path.is_file(),
            },
        }

    @app.websocket("/ws/interview/{session_id}")
    async def interview_socket(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()

        async def send_event(event: dict[str, object]) -> None:
            await websocket.send_json(event)

        try:
            pipeline = InterviewSessionPipeline(
                session_id=session_id,
                settings=active_settings,
                stt=services.stt,
                llm=services.llm,
                tts=services.tts,
                vad=_create_vad(active_settings),
                send_event=send_event,
            )
            await pipeline.start()
        except Exception as error:
            await websocket.send_json(
                {
                    "type": "error",
                    "payload": {
                        "code": "session_start_failed",
                        "message": str(error),
                    },
                }
            )
            await websocket.close(code=1011)
            return

        try:
            while True:
                message = await websocket.receive()
                if message.get("bytes") is not None:
                    await pipeline.handle_audio(message["bytes"])
                elif message.get("text") is not None:
                    try:
                        control = json.loads(message["text"])
                    except json.JSONDecodeError:
                        await send_event(
                            {"type": "error", "payload": {"code": "invalid_json"}}
                        )
                    else:
                        await pipeline.handle_control(control)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await pipeline.close()

    return app


def _create_vad(settings: Settings) -> EnergyVad | SileroOnnxVad:
    if settings.vad_backend == "energy":
        return EnergyVad()
    if settings.vad_backend == "silero":
        return SileroOnnxVad(settings.silero_model_path)
    raise ConfigurationError(f"Unsupported VAD backend: {settings.vad_backend}")
