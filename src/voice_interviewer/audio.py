from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def pcm16_bytes_to_float32(data: bytes) -> np.ndarray:
    if len(data) % 2:
        raise ValueError("PCM16 payload must contain an even number of bytes")
    samples = np.frombuffer(data, dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def float32_to_pcm16(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


@dataclass(slots=True)
class AudioFrameBuffer:
    frame_samples: int
    _pending: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.float32), init=False
    )

    def push(self, audio: np.ndarray) -> list[np.ndarray]:
        if audio.ndim != 1:
            raise ValueError("Audio must be mono")
        combined = np.concatenate((self._pending, audio.astype(np.float32, copy=False)))
        frame_count = len(combined) // self.frame_samples
        frames = [
            combined[index : index + self.frame_samples].copy()
            for index in range(0, frame_count * self.frame_samples, self.frame_samples)
        ]
        self._pending = combined[frame_count * self.frame_samples :].copy()
        return frames

    def flush(self, *, pad: bool = False) -> np.ndarray | None:
        if not len(self._pending):
            return None
        pending = self._pending
        self._pending = np.empty(0, dtype=np.float32)
        if not pad:
            return pending
        padded = np.zeros(self.frame_samples, dtype=np.float32)
        padded[: len(pending)] = pending
        return padded
