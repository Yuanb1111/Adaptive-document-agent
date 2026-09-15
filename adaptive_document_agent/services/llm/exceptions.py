"""Safe, provider-neutral LLM errors."""


class LLMError(RuntimeError):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


class PrivacyViolationError(LLMError):
    pass

