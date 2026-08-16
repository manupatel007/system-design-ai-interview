from __future__ import annotations

import numpy as np
import pytest

from voice_interviewer.vad.silero import SileroOnnxVad


def test_downloaded_silero_model_scores_silence_low(project_root) -> None:
    model_path = project_root / ".models" / "silero-vad" / "silero_vad.onnx"
    if not model_path.is_file():
        pytest.skip("Run scripts/download_models.py --silero")
    vad = SileroOnnxVad(model_path)

    scores = [vad.predict(np.zeros(512, dtype=np.float32)) for _ in range(5)]

    assert max(scores) < 0.1
