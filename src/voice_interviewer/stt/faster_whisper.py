from __future__ import annotations

import asyncio
import contextlib
import os
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
        cpu_threads: int = 2,
    ) -> None:
        self.model_name = model_name
        self.model_root = model_root
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()
        self._transcription_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def ready(self) -> bool:
        return (self.model_root / f"faster-whisper-{self.model_name}").is_dir()

    async def load(self) -> None:
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            load_job = asyncio.create_task(asyncio.to_thread(self._load_sync))
            try:
                self._model = await asyncio.shield(load_job)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    self._model = await load_job
                raise
            except RuntimeError as error:
                _raise_actionable_memory_error(error)
                raise

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
        async with self._transcription_lock:
            transcription_job = asyncio.create_task(
                asyncio.to_thread(self._transcribe_sync, audio, prompt)
            )
            try:
                return await asyncio.shield(transcription_job)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await transcription_job
                raise
            except RuntimeError as error:
                _raise_actionable_memory_error(error)
                raise

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


def _raise_actionable_memory_error(error: RuntimeError) -> None:
    message = str(error).casefold()
    if not any(
        marker in message
        for marker in ("mkl_malloc", "failed to allocate memory", "std::bad_alloc")
    ):
        return
    memory_summary = _windows_memory_summary()
    raise RuntimeError(
        "faster-whisper could not allocate CPU inference memory in MKL/CTranslate2. "
        f"{memory_summary}"
        "Close memory-heavy applications and duplicate interviewer/test processes, then "
        "restart the server. Keep the Windows page file system-managed or increase it. "
        "VOICE_STT_CPU_THREADS=1 or 2 can reduce transient scratch-memory pressure but "
        "cannot overcome an exhausted commit limit."
    ) from error


def _windows_memory_summary() -> str:
    if os.name != "nt":
        return "The host memory or commit limit is exhausted. "
    try:
        import ctypes
        from ctypes import wintypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return "The Windows memory or commit limit is exhausted. "
        mebibyte = 1024 * 1024
        available_physical = status.ullAvailPhys / mebibyte
        available_commit = status.ullAvailPageFile / mebibyte
        commit_limit = status.ullTotalPageFile / mebibyte
        return (
            f"Windows reports {available_physical:,.0f} MB available physical memory and "
            f"{available_commit:,.0f} MB available commit against a "
            f"{commit_limit:,.0f} MB commit limit. "
        )
    except (AttributeError, OSError, ValueError):
        return "The Windows memory or commit limit is exhausted. "


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
