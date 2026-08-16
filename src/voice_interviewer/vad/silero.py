from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort

from voice_interviewer.errors import ModelNotReadyError


class SileroOnnxVad:
    """Stateful NumPy wrapper around Silero VAD's published ONNX contract."""

    sample_rate = 16_000
    frame_samples = 512
    context_samples = 64

    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise ModelNotReadyError(
                f"Silero model not found at {model_path}. Run "
                "`uv run python scripts/download_models.py --silero`."
            )
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
            sess_options=options,
        )
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.context_samples), dtype=np.float32)

    def predict(self, frame: np.ndarray) -> float:
        if frame.shape != (self.frame_samples,):
            raise ValueError(
                f"Silero expects {self.frame_samples} samples, received {frame.shape}"
            )
        model_input = np.concatenate(
            (self._context, frame.astype(np.float32, copy=False)[None, :]), axis=1
        )
        output, next_state = self._session.run(
            None,
            {
                "input": model_input,
                "state": self._state,
                "sr": np.array(self.sample_rate, dtype=np.int64),
            },
        )
        self._state = next_state
        self._context = model_input[:, -self.context_samples :]
        return float(output.squeeze())
