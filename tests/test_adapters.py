from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from voice_interviewer.adapters import create_tts
from voice_interviewer.errors import ConfigurationError
from voice_interviewer.llm.databricks import DatabricksLLM
from voice_interviewer.llm.mock import MockInterviewLLM
from voice_interviewer.models import InterviewContext
from voice_interviewer.tts.kokoro import KokoroTTS
from voice_interviewer.tts.mock import ToneMockTTS
from voice_interviewer.tts.piper import PiperTTS


@pytest.mark.asyncio
async def test_mock_llm_grounds_question_in_transcript() -> None:
    response = await MockInterviewLLM().respond(
        InterviewContext(session_id="test", transcript="I will add Redis as a cache")
    )
    assert "cache" in response.lower()


@pytest.mark.asyncio
async def test_mock_tts_returns_pcm_audio() -> None:
    output = await ToneMockTTS().synthesize("What happens when the database fails?")
    assert output.sample_rate == 16_000
    assert len(output.pcm_s16le) > 1_000
    assert len(output.pcm_s16le) % 2 == 0
    assert np.frombuffer(output.pcm_s16le, dtype="<i2").any()


def test_create_tts_uses_kokoro_settings(mock_settings) -> None:
    tts = create_tts(replace(mock_settings, tts_backend="kokoro", tts_speed=1.15))

    assert isinstance(tts, KokoroTTS)
    assert tts.voice == "af_heart"
    assert tts.language == "en-us"
    assert tts.speed == 1.15


def test_create_tts_uses_piper_settings(mock_settings) -> None:
    tts = create_tts(replace(mock_settings, tts_backend="piper", tts_speed=1.2))

    assert isinstance(tts, PiperTTS)
    assert tts.model_path == mock_settings.piper_model_path
    assert tts.config_path == mock_settings.piper_config_path
    assert tts.speed == 1.2


def test_databricks_requires_configuration() -> None:
    with pytest.raises(ConfigurationError):
        DatabricksLLM(host=None, token=None, model="model")


def test_databricks_extracts_responses_text() -> None:
    payload = {
        "output": [
            {
                "content": [
                    {"type": "output_text", "text": "How would this fail?"}
                ]
            }
        ]
    }
    assert DatabricksLLM._extract_text(payload) == "How would this fail?"
