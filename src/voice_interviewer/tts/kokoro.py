from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import numpy as np

from voice_interviewer.audio import float32_to_pcm16
from voice_interviewer.errors import ConfigurationError, ModelNotReadyError
from voice_interviewer.models import AudioOutput


class KokoroTTS:
    def __init__(
        self,
        *,
        model_path: Path,
        voices_path: Path,
        voice: str = "af_heart",
        language: str = "en-us",
        speed: float = 1.0,
    ) -> None:
        if not 0.5 <= speed <= 2.0:
            raise ConfigurationError("Kokoro speed must be between 0.5 and 2.0")
        self.model_path = model_path
        self.voices_path = voices_path
        self.voice = voice
        self.language = language
        self.speed = speed
        self._engine: Any | None = None
        self._load_lock = asyncio.Lock()
        self._synthesis_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._engine is not None

    @property
    def ready(self) -> bool:
        return self.model_path.is_file() and self.voices_path.is_file()

    async def load(self) -> None:
        if self._engine is not None:
            return
        async with self._load_lock:
            if self._engine is not None:
                return
            load_job = asyncio.create_task(asyncio.to_thread(self._load_sync))
            try:
                self._engine = await asyncio.shield(load_job)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    self._engine = await load_job
                raise

    def _load_sync(self) -> Any:
        missing = [path.name for path in (self.model_path, self.voices_path) if not path.is_file()]
        if missing:
            names = ", ".join(missing)
            raise ModelNotReadyError(
                f"Missing Kokoro files: {names}. Run scripts/download_models.py --kokoro."
            )
        from kokoro_onnx import Kokoro

        engine = Kokoro(str(self.model_path), str(self.voices_path))
        if self.voice not in engine.voices:
            raise ConfigurationError(f"Unknown Kokoro voice: {self.voice}")
        return engine

    async def synthesize(self, text: str) -> AudioOutput:
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("TTS text must not be empty")
        await self.load()
        async with self._synthesis_lock:
            synthesis_job = asyncio.create_task(
                asyncio.to_thread(self._synthesize_sync, normalized_text)
            )
            try:
                return await asyncio.shield(synthesis_job)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await synthesis_job
                raise

    def _synthesize_sync(self, text: str) -> AudioOutput:
        if self._engine is None:
            raise RuntimeError("Kokoro model was not loaded")
        audio, sample_rate = self._engine.create(
            text,
            voice=self.voice,
            speed=self.speed,
            lang=self.language,
        )
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(samples):
            raise RuntimeError("Kokoro returned empty audio")
        return AudioOutput(
            pcm_s16le=float32_to_pcm16(samples),
            sample_rate=int(sample_rate),
        )
