from __future__ import annotations

import asyncio
import math

import numpy as np

from voice_interviewer.audio import float32_to_pcm16
from voice_interviewer.models import AudioOutput


class ToneMockTTS:
    """Deterministic audible placeholder that exercises the complete audio path."""

    def __init__(self, sample_rate: int = 16_000) -> None:
        self.sample_rate = sample_rate

    async def synthesize(self, text: str) -> AudioOutput:
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> AudioOutput:
        word_count = max(1, min(len(text.split()), 24))
        tone_seconds = 0.055
        gap_seconds = 0.035
        tone_samples = int(self.sample_rate * tone_seconds)
        gap = np.zeros(int(self.sample_rate * gap_seconds), dtype=np.float32)
        parts: list[np.ndarray] = []
        for index in range(word_count):
            frequency = 330.0 + (index % 5) * 55.0
            timeline = np.arange(tone_samples, dtype=np.float32) / self.sample_rate
            envelope = np.sin(np.linspace(0, math.pi, tone_samples, dtype=np.float32))
            tone = 0.08 * np.sin(2 * math.pi * frequency * timeline) * envelope
            parts.extend((tone.astype(np.float32), gap))
        audio = np.concatenate(parts)
        return AudioOutput(pcm_s16le=float32_to_pcm16(audio), sample_rate=self.sample_rate)
