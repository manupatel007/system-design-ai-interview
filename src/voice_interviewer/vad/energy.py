from __future__ import annotations

import numpy as np


class EnergyVad:
    """Dependency-free development VAD; production defaults to Silero."""

    frame_samples = 512

    def __init__(self, speech_rms: float = 0.02) -> None:
        self.speech_rms = speech_rms

    def reset(self) -> None:
        return None

    def predict(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float32)))
        return min(1.0, rms / self.speech_rms)
