class VoicePipelineError(Exception):
    """Base error for expected voice-pipeline failures."""


class ModelNotReadyError(VoicePipelineError):
    """Raised when a configured local model has not been downloaded."""


class ConfigurationError(VoicePipelineError):
    """Raised when a provider is selected without its required configuration."""


class LLMProviderError(VoicePipelineError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
