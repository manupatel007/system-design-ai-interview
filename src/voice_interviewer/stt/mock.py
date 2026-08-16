from __future__ import annotations

import numpy as np

from voice_interviewer.models import Transcript


class MockSTT:
    def __init__(self, transcript: str = "I would place a cache in front of the database.") -> None:
        self.transcript = transcript

    async def transcribe(
        self, audio: np.ndarray, *, prompt: str | None = None
    ) -> Transcript:
        return Transcript(
            text=self.transcript,
            language="en",
            duration_seconds=float(len(audio) / 16_000),
        )
