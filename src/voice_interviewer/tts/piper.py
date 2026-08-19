from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from voice_interviewer.errors import ConfigurationError, ModelNotReadyError
from voice_interviewer.models import AudioOutput

_END_OF_STREAM = object()


class PiperTTS:
    def __init__(
        self,
        *,
        model_path: Path,
        config_path: Path,
        speed: float = 1.0,
    ) -> None:
        if not 0.5 <= speed <= 2.0:
            raise ConfigurationError("Piper speed must be between 0.5 and 2.0")
        self.model_path = model_path
        self.config_path = config_path
        self.speed = speed
        self._engine: Any | None = None
        self._load_lock = asyncio.Lock()
        self._synthesis_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._engine is not None

    @property
    def ready(self) -> bool:
        return self.model_path.is_file() and self.config_path.is_file()

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
        missing = [
            path.name for path in (self.model_path, self.config_path) if not path.is_file()
        ]
        if missing:
            names = ", ".join(missing)
            raise ModelNotReadyError(
                f"Missing Piper files: {names}. Run scripts/download_models.py --piper."
            )
        from piper import PiperVoice

        return PiperVoice.load(self.model_path, self.config_path)

    async def synthesize(self, text: str) -> AudioOutput:
        chunks = [chunk async for chunk in self.synthesize_stream(text)]
        if not chunks:
            raise RuntimeError("Piper returned empty audio")
        sample_rate = chunks[0].sample_rate
        channels = chunks[0].channels
        if any(
            chunk.sample_rate != sample_rate or chunk.channels != channels
            for chunk in chunks[1:]
        ):
            raise RuntimeError("Piper returned incompatible audio chunks")
        return AudioOutput(
            pcm_s16le=b"".join(chunk.pcm_s16le for chunk in chunks),
            sample_rate=sample_rate,
            channels=channels,
        )

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioOutput]:
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("TTS text must not be empty")
        await self.load()
        async with self._synthesis_lock:
            iterator = self._create_iterator(normalized_text)
            while True:
                chunk = await self._next_chunk(iterator)
                if chunk is _END_OF_STREAM:
                    return
                yield self._to_audio_output(chunk)

    def _create_iterator(self, text: str) -> Iterator[Any]:
        if self._engine is None:
            raise RuntimeError("Piper model was not loaded")
        from piper import SynthesisConfig

        synthesis_config = SynthesisConfig(length_scale=1.0 / self.speed)
        return iter(self._engine.synthesize(text, syn_config=synthesis_config))

    async def _next_chunk(self, iterator: Iterator[Any]) -> Any:
        synthesis_job = asyncio.create_task(
            asyncio.to_thread(next, iterator, _END_OF_STREAM)
        )
        try:
            return await asyncio.shield(synthesis_job)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await synthesis_job
            raise

    @staticmethod
    def _to_audio_output(chunk: Any) -> AudioOutput:
        if int(chunk.sample_width) != 2:
            raise RuntimeError("Piper returned audio that is not PCM16")
        sample_rate = int(chunk.sample_rate)
        channels = int(chunk.sample_channels)
        if sample_rate <= 0 or channels != 1:
            raise RuntimeError("Piper returned an unsupported audio format")
        pcm_s16le = bytes(chunk.audio_int16_bytes)
        if not pcm_s16le or len(pcm_s16le) % 2:
            raise RuntimeError("Piper returned an empty audio chunk")
        return AudioOutput(
            pcm_s16le=pcm_s16le,
            sample_rate=sample_rate,
            channels=channels,
        )
