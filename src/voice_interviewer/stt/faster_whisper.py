from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np

from voice_interviewer.models import Transcript, TranscriptSegment


class FasterWhisperSTT:
    def __init__(
        self,
        *,
        model_name: str,
        model_root: Path,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 4,
    ) -> None:
        self.model_name = model_name
        self.model_root = model_root
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    async def load(self) -> None:
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> Any:
        from faster_whisper import WhisperModel

        local_model = self.model_root / f"faster-whisper-{self.model_name}"
        source = str(local_model) if local_model.is_dir() else self.model_name
        self.model_root.mkdir(parents=True, exist_ok=True)
        return WhisperModel(
            source,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
            download_root=str(self.model_root),
            local_files_only=local_model.is_dir(),
        )

    async def transcribe(
        self, audio: np.ndarray, *, prompt: str | None = None
    ) -> Transcript:
        await self.load()
        return await asyncio.to_thread(self._transcribe_sync, audio, prompt)

    def _transcribe_sync(self, audio: np.ndarray, prompt: str | None) -> Transcript:
        if self._model is None:
            raise RuntimeError("Whisper model was not loaded")
        segment_iterator, info = self._model.transcribe(
            audio.astype(np.float32, copy=False),
            language="en",
            task="transcribe",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=prompt,
            vad_filter=False,
            word_timestamps=False,
        )
        segments = tuple(
            TranscriptSegment(
                start_seconds=segment.start,
                end_seconds=segment.end,
                text=segment.text.strip(),
                average_log_probability=getattr(segment, "avg_logprob", None),
            )
            for segment in segment_iterator
        )
        text = " ".join(segment.text for segment in segments if segment.text).strip()
        return Transcript(
            text=text,
            language=getattr(info, "language", "en"),
            duration_seconds=float(len(audio) / 16_000),
            segments=segments,
        )
