class VoicePipelineError(Exception):
    """Base error for expected voice-pipeline failures."""


class ModelNotReadyError(VoicePipelineError):
    """Raised when a configured local model has not been downloaded."""


class ConfigurationError(VoicePipelineError):
    """Raised when a provider is selected without its required configuration."""
