from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import numpy as np

from voice_interviewer.models import Transcript, TranscriptSegment

_MAX_COMPRESSION_RATIO = 2.4
_MIN_AVERAGE_LOG_PROBABILITY = -1.0
_MAX_NO_SPEECH_PROBABILITY = 0.6
_NO_SPEECH_LOG_PROBABILITY = -0.5
_SHORT_FRAGMENT_SECONDS = 0.8
_INCOMPLETE_SHORT_WORDS = frozenset({"a", "an", "and", "i", "so", "the", "you"})


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
            hotwords=prompt,
            vad_filter=False,
            word_timestamps=False,
        )
        duration_seconds = float(len(audio) / 16_000)
        accepted_segments: list[TranscriptSegment] = []
        for segment in segment_iterator:
            text = segment.text.strip()
            average_log_probability = _optional_float(segment, "avg_logprob")
            no_speech_probability = _optional_float(segment, "no_speech_prob")
            compression_ratio = _optional_float(segment, "compression_ratio")
            if not _is_reliable_segment(
                text=text,
                audio_duration_seconds=duration_seconds,
                average_log_probability=average_log_probability,
                no_speech_probability=no_speech_probability,
                compression_ratio=compression_ratio,
            ):
                continue
            accepted_segments.append(
                TranscriptSegment(
                    start_seconds=segment.start,
                    end_seconds=segment.end,
                    text=text,
                    average_log_probability=average_log_probability,
                    no_speech_probability=no_speech_probability,
                    compression_ratio=compression_ratio,
                )
            )
        segments = tuple(accepted_segments)
        text = " ".join(segment.text for segment in segments if segment.text).strip()
        return Transcript(
            text=text,
            language=getattr(info, "language", "en"),
            duration_seconds=duration_seconds,
            segments=segments,
        )


def _optional_float(value: object, attribute: str) -> float | None:
    result = getattr(value, attribute, None)
    return float(result) if result is not None else None


def _is_reliable_segment(
    *,
    text: str,
    audio_duration_seconds: float,
    average_log_probability: float | None,
    no_speech_probability: float | None,
    compression_ratio: float | None,
) -> bool:
    if not text:
        return False
    if compression_ratio is not None and compression_ratio > _MAX_COMPRESSION_RATIO:
        return False
    if (
        average_log_probability is not None
        and average_log_probability < _MIN_AVERAGE_LOG_PROBABILITY
    ):
        return False
    if (
        no_speech_probability is not None
        and no_speech_probability > _MAX_NO_SPEECH_PROBABILITY
        and (
            average_log_probability is None
            or average_log_probability < _NO_SPEECH_LOG_PROBABILITY
        )
    ):
        return False
    normalized_words = re.findall(r"[a-z]+", text.casefold())
    return not (
        audio_duration_seconds < _SHORT_FRAGMENT_SECONDS
        and len(normalized_words) == 1
        and normalized_words[0] in _INCOMPLETE_SHORT_WORDS
    )
