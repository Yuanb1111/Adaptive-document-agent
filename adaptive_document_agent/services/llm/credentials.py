"""Provider/endpoint identities for session credentials and explicit transport."""

from hashlib import sha256

from .config import LLMSettings, ProviderName


# Keep destinations explicit: SDK environment fallbacks must not reroute a key.
DEFAULT_ENDPOINTS = {
    ProviderName.OPENAI: "https://api.openai.com/v1",
    ProviderName.DEEPSEEK: "https://api.deepseek.com/beta",
    ProviderName.GEMINI: "https://generativelanguage.googleapis.com",
    ProviderName.OPENROUTER: "https://openrouter.ai/api/v1",
    ProviderName.OLLAMA: "http://localhost:11434",
}


def provider_endpoint(provider: ProviderName, base_url: str | None) -> str | None:
    return (base_url or "").strip().rstrip("/") or DEFAULT_ENDPOINTS.get(provider)


def credential_scope(provider: ProviderName, base_url: str | None) -> str:
    """A widget identity containing neither a credential nor a raw custom URL."""
    endpoint = provider_endpoint(provider, base_url) or ""
    return sha256(f"{provider.value}|{endpoint}".encode()).hexdigest()


def configured_credential(
    defaults: LLMSettings, provider: ProviderName, base_url: str | None, *, public_deployment: bool,
) -> str | None:
    """Reuse configured credentials only for their exact provider/endpoint pair."""
    if public_deployment or not defaults.api_key:
        return None
    if credential_scope(provider, base_url) != credential_scope(defaults.provider, defaults.base_url):
        return None
    return defaults.api_key.get_secret_value()
