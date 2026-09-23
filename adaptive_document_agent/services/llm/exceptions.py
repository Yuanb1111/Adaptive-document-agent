"""Safe, provider-neutral LLM errors."""


class LLMError(RuntimeError):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


class LLMTransportError(LLMResponseError):
    """Request failed before usable output; never trigger JSON regeneration."""

    def __init__(self, message, *, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


class LLMStructuredOutputError(LLMResponseError):
    """Only this error carries invalid output eligible for one format repair."""

    def __init__(self, message, *, response):
        super().__init__(message)
        self.response = response


class PrivacyViolationError(LLMError):
    pass
