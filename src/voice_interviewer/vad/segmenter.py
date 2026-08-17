from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class SegmentEventType(StrEnum):
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"


@dataclass(frozen=True, slots=True)
class SegmentEvent:
    type: SegmentEventType
    audio: np.ndarray | None = None


class SpeechSegmenter:
    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        frame_samples: int = 512,
        threshold: float = 0.5,
        negative_threshold: float = 0.35,
        min_speech_ms: int = 192,
        min_silence_ms: int = 1_200,
        prefix_padding_ms: int = 256,
        trailing_padding_ms: int = 160,
    ) -> None:
        if negative_threshold >= threshold:
            raise ValueError("negative_threshold must be lower than threshold")
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self.threshold = threshold
        self.negative_threshold = negative_threshold
        self.frame_ms = frame_samples * 1000 / sample_rate
        self.min_speech_frames = max(1, math.ceil(min_speech_ms / self.frame_ms))
        self.min_silence_frames = max(1, math.ceil(min_silence_ms / self.frame_ms))
        self.prefix_frames = max(1, math.ceil(prefix_padding_ms / self.frame_ms))
        self.trailing_frames = max(1, math.ceil(trailing_padding_ms / self.frame_ms))
        self._pre_roll: deque[np.ndarray] = deque(maxlen=self.prefix_frames)
        self._active_frames: list[np.ndarray] = []
        self._speech_frames = 0
        self._silence_frames = 0
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def push(self, frame: np.ndarray, probability: float) -> list[SegmentEvent]:
        if frame.shape != (self.frame_samples,):
            raise ValueError(f"Expected frame shape {(self.frame_samples,)}, got {frame.shape}")

        if not self._active:
            self._pre_roll.append(frame.copy())
            if probability >= self.threshold:
                self._speech_frames += 1
            elif probability < self.negative_threshold:
                self._speech_frames = 0

            if self._speech_frames < self.min_speech_frames:
                return []

            self._active = True
            self._active_frames = list(self._pre_roll)
            self._pre_roll.clear()
            self._silence_frames = 0
            return [SegmentEvent(SegmentEventType.SPEECH_STARTED)]

        self._active_frames.append(frame.copy())
        if probability < self.negative_threshold:
            self._silence_frames += 1
        elif probability >= self.threshold:
            self._silence_frames = 0

        if self._silence_frames < self.min_silence_frames:
            return []

        trim_count = max(0, self._silence_frames - self.trailing_frames)
        kept_frames = (
            self._active_frames[:-trim_count] if trim_count else self._active_frames
        )
        audio = np.concatenate(kept_frames).astype(np.float32, copy=False)
        trailing = self._active_frames[-self.prefix_frames :]
        self._reset_after_segment(trailing)
        return [SegmentEvent(SegmentEventType.SPEECH_ENDED, audio)]

    def flush(self) -> SegmentEvent | None:
        if not self._active_frames:
            self.reset()
            return None
        audio = np.concatenate(self._active_frames).astype(np.float32, copy=False)
        self.reset()
        return SegmentEvent(SegmentEventType.SPEECH_ENDED, audio)

    def reset(self) -> None:
        self._pre_roll.clear()
        self._active_frames = []
        self._speech_frames = 0
        self._silence_frames = 0
        self._active = False

    def _reset_after_segment(self, trailing: list[np.ndarray]) -> None:
        self._active_frames = []
        self._speech_frames = 0
        self._silence_frames = 0
        self._active = False
        self._pre_roll.clear()
        self._pre_roll.extend(frame.copy() for frame in trailing)
