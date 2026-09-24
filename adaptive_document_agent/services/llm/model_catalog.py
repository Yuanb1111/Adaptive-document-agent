"""Provider model discovery with safe, provider-specific fallbacks."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .config import ProviderName


RECOMMENDED_MODELS: dict[ProviderName, tuple[str, ...]] = {
    ProviderName.DEEPSEEK: ("deepseek-flash", "deepseek-v4-pro"),
    ProviderName.OPENAI: ("gpt-6-sol", "gpt-6-astra", "gpt-6-luna"),
    ProviderName.GEMINI: ("gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.7-flash"),
    ProviderName.OPENROUTER: (
        "openai/gpt-6-sol",
        "google/gemini-3.8-flash",
        "deepseek/deepseek-v4-pro",
    ),
    ProviderName.OLLAMA: ("llama3.1",),
    ProviderName.OPENAI_COMPATIBLE: (),
    ProviderName.MOCK: ("mock",),
}

_NON_TEXT_MARKERS = (
    "audio",
    "embedding",
    "image",
    "live",
    "moderation",
    "realtime",
    "robotics",
    "search-preview",
    "transcribe",
    "tts",
    "video",
    "whisper",
)


class ModelCatalogError(RuntimeError):
    """A model catalog could not be retrieved or parsed."""


def recommended_models(provider: ProviderName) -> list[str]:
    return list(RECOMMENDED_MODELS.get(provider, ()))


def list_provider_models(
    provider: ProviderName,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 5.0,
) -> list[str]:
    """Return currently available text-generation models from a provider."""
    if provider in {ProviderName.OPENAI, ProviderName.DEEPSEEK, ProviderName.GEMINI} and not api_key:
        raise ModelCatalogError("An API key is required to load this provider's live model list.")

    url, headers = _request_config(provider, api_key=api_key, base_url=base_url)
    payload = _request_json(url, headers, timeout_seconds)
    models = _models_from_payload(provider, payload)
    if not models:
        raise ModelCatalogError("The provider returned no compatible text-generation models.")
    return models


def _request_config(
    provider: ProviderName,
    *,
    api_key: str | None,
    base_url: str | None,
) -> tuple[str, dict[str, str]]:
    headers = {"Accept": "application/json"}
    if provider == ProviderName.GEMINI:
        headers["x-goog-api-key"] = api_key or ""
        return "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", headers
    if provider == ProviderName.OLLAMA:
        root = (base_url or "http://localhost:11434").rstrip("/") + "/"
        return urljoin(root, "api/tags"), headers

    defaults = {
        ProviderName.OPENAI: "https://api.openai.com/v1",
        ProviderName.DEEPSEEK: "https://api.deepseek.com",
        ProviderName.OPENROUTER: "https://openrouter.ai/api/v1",
    }
    root = (base_url or defaults.get(provider) or "").rstrip("/") + "/"
    if not root.strip("/"):
        raise ModelCatalogError("A base URL is required to discover models from this provider.")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return urljoin(root, "models"), headers


def _request_json(url: str, headers: dict[str, str], timeout_seconds: float) -> dict[str, Any]:
    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - provider URLs are controlled above
            raw = response.read(2_000_000)
        payload = json.loads(raw)
    except Exception as exc:
        raise ModelCatalogError(f"Live model discovery failed ({type(exc).__name__}).") from exc
    if not isinstance(payload, dict):
        raise ModelCatalogError("The provider returned an invalid model catalog.")
    return payload


def _models_from_payload(provider: ProviderName, payload: dict[str, Any]) -> list[str]:
    if provider == ProviderName.OLLAMA:
        candidates = [item.get("name") for item in payload.get("models", []) if isinstance(item, dict)]
    elif provider == ProviderName.GEMINI:
        candidates = []
        for item in payload.get("models", []):
            if not isinstance(item, dict):
                continue
            methods = item.get("supportedGenerationMethods", [])
            if methods and "generateContent" not in methods:
                continue
            candidates.append(item.get("baseModelId") or str(item.get("name", "")).removeprefix("models/"))
    else:
        candidates = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]

    cleaned = {
        value.strip()
        for value in candidates
        if isinstance(value, str) and value.strip() and _is_text_model(provider, value)
    }
    return sorted(cleaned, key=str.casefold)


def _is_text_model(provider: ProviderName, model: str) -> bool:
    lowered = model.casefold()
    if provider == ProviderName.OLLAMA:
        return True
    return not any(marker in lowered for marker in _NON_TEXT_MARKERS)
