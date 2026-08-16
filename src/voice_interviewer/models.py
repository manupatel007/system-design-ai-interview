from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    average_log_probability: float | None = None


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    duration_seconds: float
    segments: tuple[TranscriptSegment, ...] = ()


@dataclass(frozen=True, slots=True)
class InterviewContext:
    session_id: str
    problem: str | None = None
    transcript: str = ""
    recent_diagram_delta: str | None = None
    selected_object_ids: tuple[str, ...] = ()
    glossary: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AudioOutput:
    pcm_s16le: bytes
    sample_rate: int
    channels: int = 1


class SpeechToText(Protocol):
    async def transcribe(
        self, audio: np.ndarray, *, prompt: str | None = None
    ) -> Transcript: ...


class InterviewLanguageModel(Protocol):
    async def respond(self, context: InterviewContext) -> str: ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str) -> AudioOutput: ...


class VoiceActivityDetector(Protocol):
    frame_samples: int

    def predict(self, frame: np.ndarray) -> float: ...

    def reset(self) -> None: ...
