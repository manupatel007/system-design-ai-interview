from __future__ import annotations

from voice_interviewer.config import Settings
from voice_interviewer.errors import ConfigurationError
from voice_interviewer.llm import DatabricksLLM, MockInterviewLLM
from voice_interviewer.models import InterviewLanguageModel, SpeechToText, TextToSpeech
from voice_interviewer.stt import FasterWhisperSTT, MockSTT
from voice_interviewer.tts import ToneMockTTS


def create_stt(settings: Settings) -> SpeechToText:
    if settings.stt_backend == "mock":
        return MockSTT()
    if settings.stt_backend == "faster-whisper":
        return FasterWhisperSTT(
            model_name=settings.stt_model,
            model_root=settings.model_root,
            device=settings.stt_device,
            compute_type=settings.stt_compute_type,
            cpu_threads=settings.stt_cpu_threads,
        )
    raise ConfigurationError(f"Unsupported STT backend: {settings.stt_backend}")


def create_llm(settings: Settings) -> InterviewLanguageModel:
    if settings.llm_backend == "mock":
        return MockInterviewLLM()
    if settings.llm_backend == "databricks":
        return DatabricksLLM(
            host=settings.databricks_host,
            token=settings.databricks_token,
            model=settings.databricks_model,
        )
    raise ConfigurationError(f"Unsupported LLM backend: {settings.llm_backend}")


def create_tts(settings: Settings) -> TextToSpeech:
    if settings.tts_backend == "mock":
        return ToneMockTTS(sample_rate=settings.sample_rate)
    raise ConfigurationError(f"Unsupported TTS backend: {settings.tts_backend}")
