from __future__ import annotations

import numpy as np

from voice_interviewer.vad.segmenter import SegmentEventType, SpeechSegmenter


def test_segmenter_emits_single_trimmed_utterance() -> None:
    segmenter = SpeechSegmenter(
        sample_rate=16_000,
        frame_samples=512,
        min_speech_ms=64,
        min_silence_ms=96,
        prefix_padding_ms=64,
        trailing_padding_ms=32,
    )
    silence = np.zeros(512, dtype=np.float32)
    speech = np.full(512, 0.1, dtype=np.float32)
    events = []

    for frame, probability in [
        (silence, 0.0),
        (speech, 0.9),
        (speech, 0.9),
        (speech, 0.9),
        (silence, 0.0),
        (silence, 0.0),
        (silence, 0.0),
    ]:
        events.extend(segmenter.push(frame, probability))

    assert [event.type for event in events] == [
        SegmentEventType.SPEECH_STARTED,
        SegmentEventType.SPEECH_ENDED,
    ]
    assert events[-1].audio is not None
    assert len(events[-1].audio) < 7 * 512
    assert not segmenter.active


def test_segmenter_flushes_active_audio() -> None:
    segmenter = SpeechSegmenter(min_speech_ms=32)
    speech = np.full(512, 0.1, dtype=np.float32)
    segmenter.push(speech, 0.9)

    event = segmenter.flush()

    assert event is not None
    assert event.type is SegmentEventType.SPEECH_ENDED
    assert event.audio is not None
