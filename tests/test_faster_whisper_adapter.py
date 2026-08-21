from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

import numpy as np
import pytest

from voice_interviewer.config import PROJECT_ROOT
from voice_interviewer.models import Transcript
from voice_interviewer.stt import faster_whisper as faster_whisper_module
from voice_interviewer.stt.faster_whisper import FasterWhisperSTT


@dataclass
class FakeSegment:
    text: str
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    start: float = 0.0
    end: float = 1.0


class FakeInfo:
    language = "en"


class FakeWhisperModel:
    def __init__(self, segments: list[FakeSegment]) -> None:
        self.segments = segments
        self.options: dict[str, object] = {}

    def transcribe(self, _audio, **options):
        self.options = options
        return iter(self.segments), FakeInfo()


def _transcriber(segments: list[FakeSegment]) -> tuple[FasterWhisperSTT, FakeWhisperModel]:
    transcriber = FasterWhisperSTT(model_name="base.en", model_root=PROJECT_ROOT / ".models")
    model = FakeWhisperModel(segments)
    transcriber._model = model
    return transcriber, model


@pytest.mark.asyncio
async def test_cancelled_load_finishes_once_and_keeps_model(monkeypatch) -> None:
    transcriber = FasterWhisperSTT(
        model_name="base.en",
        model_root=PROJECT_ROOT / ".models",
    )
    started = threading.Event()
    release = threading.Event()
    model = object()
    calls = 0

    def load_sync():
        nonlocal calls
        calls += 1
        started.set()
        release.wait(1)
        return model

    monkeypatch.setattr(transcriber, "_load_sync", load_sync)
    load_task = asyncio.create_task(transcriber.load())
    assert await asyncio.to_thread(started.wait, 1)

    load_task.cancel()
    await asyncio.sleep(0)
    assert not load_task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await load_task

    assert transcriber._model is model
    await transcriber.load()
    assert calls == 1


@pytest.mark.asyncio
async def test_transcriptions_are_serialized_across_callers(monkeypatch) -> None:
    transcriber, _ = _transcriber([])
    started = threading.Event()
    release = threading.Event()
    guard = threading.Lock()
    calls = 0
    active = 0
    peak = 0

    def transcribe_sync(audio, prompt):
        nonlocal active, calls, peak
        with guard:
            calls += 1
            active += 1
            peak = max(peak, active)
            started.set()
        release.wait(1)
        with guard:
            active -= 1
        return Transcript(text="ok", language="en", duration_seconds=1.0)

    monkeypatch.setattr(transcriber, "_transcribe_sync", transcribe_sync)
    audio = np.zeros(16_000, dtype=np.float32)
    first = asyncio.create_task(transcriber.transcribe(audio))
    second = asyncio.create_task(transcriber.transcribe(audio))
    assert await asyncio.to_thread(started.wait, 1)
    await asyncio.sleep(0.02)

    assert calls == 1
    assert peak == 1
    release.set()
    results = await asyncio.gather(first, second)
    assert [result.text for result in results] == ["ok", "ok"]
    assert calls == 2
    assert peak == 1


@pytest.mark.asyncio
async def test_cancelled_transcription_drains_before_next_caller(monkeypatch) -> None:
    transcriber, _ = _transcriber([])
    started = threading.Event()
    release = threading.Event()
    guard = threading.Lock()
    calls = 0
    active = 0
    peak = 0

    def transcribe_sync(audio, prompt):
        nonlocal active, calls, peak
        with guard:
            calls += 1
            active += 1
            peak = max(peak, active)
            started.set()
        release.wait(1)
        with guard:
            active -= 1
        return Transcript(text="ok", language="en", duration_seconds=1.0)

    monkeypatch.setattr(transcriber, "_transcribe_sync", transcribe_sync)
    audio = np.zeros(16_000, dtype=np.float32)
    cancelled = asyncio.create_task(transcriber.transcribe(audio))
    assert await asyncio.to_thread(started.wait, 1)
    cancelled.cancel()
    await asyncio.sleep(0)
    next_call = asyncio.create_task(transcriber.transcribe(audio))
    await asyncio.sleep(0.02)

    assert calls == 1
    assert peak == 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert (await next_call).text == "ok"
    assert calls == 2
    assert peak == 1


@pytest.mark.asyncio
async def test_mkl_allocation_failure_has_actionable_memory_context(monkeypatch) -> None:
    transcriber, _ = _transcriber([])

    def fail_transcription(audio, prompt):
        raise RuntimeError("mkl_malloc: failed to allocate memory")

    monkeypatch.setattr(transcriber, "_transcribe_sync", fail_transcription)
    monkeypatch.setattr(
        faster_whisper_module,
        "_windows_memory_summary",
        lambda: (
            "Windows reports 900 MB available physical memory and 1,024 MB available "
            "commit against a 32,000 MB commit limit. "
        ),
    )

    with pytest.raises(RuntimeError, match="1,024 MB available commit") as captured:
        await transcriber.transcribe(np.zeros(16_000, dtype=np.float32))

    assert "Windows page file" in str(captured.value)
    assert isinstance(captured.value.__cause__, RuntimeError)


def test_glossary_is_sent_as_hotwords_not_initial_prompt() -> None:
    transcriber, model = _transcriber(
        [FakeSegment("Redis is the cache.", -0.2, 0.02, 1.1)],
    )

    result = transcriber._transcribe_sync(
        np.zeros(16_000, dtype=np.float32),
        "Kafka, Redis, PostgreSQL",
    )

    assert model.options["hotwords"] == "Kafka, Redis, PostgreSQL"
    assert "initial_prompt" not in model.options
    assert result.text == "Redis is the cache."
    assert result.segments[0].no_speech_probability == pytest.approx(0.02)
    assert result.segments[0].compression_ratio == pytest.approx(1.1)


@pytest.mark.parametrize(
    ("segment", "duration_seconds"),
    [
        (FakeSegment("System design interview.", -0.82, 0.63, 0.75), 0.35),
        (FakeSegment("S-S-S-S-S-S-S-S", -0.06, 0.30, 14.1), 0.60),
        (FakeSegment("and the other one", -1.87, 0.54, 0.75), 0.35),
        (FakeSegment("and", -0.90, 0.35, 0.27), 0.60),
    ],
)
def test_unreliable_short_decodes_are_rejected(segment, duration_seconds) -> None:
    transcriber, _ = _transcriber([segment])
    audio = np.zeros(round(duration_seconds * 16_000), dtype=np.float32)

    result = transcriber._transcribe_sync(audio, "Kafka, Redis")

    assert result.text == ""
    assert result.segments == ()


def test_confident_short_answer_is_retained() -> None:
    transcriber, _ = _transcriber(
        [FakeSegment("Yes.", -0.22, 0.08, 0.4, end=0.6)],
    )

    result = transcriber._transcribe_sync(
        np.zeros(round(0.6 * 16_000), dtype=np.float32),
        "Kafka, Redis",
    )

    assert result.text == "Yes."
