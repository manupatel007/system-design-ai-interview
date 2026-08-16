from __future__ import annotations

import numpy as np
import pytest

from voice_interviewer.audio import (
    AudioFrameBuffer,
    float32_to_pcm16,
    pcm16_bytes_to_float32,
)


def test_pcm_round_trip() -> None:
    source = np.array([-1.0, -0.25, 0.0, 0.25, 1.0], dtype=np.float32)
    restored = pcm16_bytes_to_float32(float32_to_pcm16(source))
    np.testing.assert_allclose(restored, source, atol=1 / 32768)


def test_pcm_rejects_partial_sample() -> None:
    with pytest.raises(ValueError, match="even number"):
        pcm16_bytes_to_float32(b"\x00")


def test_frame_buffer_preserves_remainder() -> None:
    buffer = AudioFrameBuffer(frame_samples=4)
    first = buffer.push(np.arange(3, dtype=np.float32))
    second = buffer.push(np.arange(3, 7, dtype=np.float32))

    assert first == []
    assert len(second) == 1
    np.testing.assert_array_equal(second[0], np.arange(4, dtype=np.float32))
    np.testing.assert_array_equal(buffer.flush(), np.arange(4, 7, dtype=np.float32))
