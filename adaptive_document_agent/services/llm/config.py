"""Environment-backed provider and privacy settings."""

import os
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, field_validator


class ProviderName(StrEnum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    MOCK = "mock"


class PrivacyMode(StrEnum):
    AUTO = "auto"
    CLOUD = "cloud"
    LOCAL_ONLY = "local_only"


class LLMSettings(BaseModel):
    provider: ProviderName = ProviderName.OLLAMA
    model: str = ""
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=120.0, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    privacy_mode: PrivacyMode = PrivacyMode.AUTO
    stage_models: dict[str, str] = Field(default_factory=dict)
    discovery_workers: int = Field(default=3, ge=1, le=4)

    @field_validator("base_url")
    @classmethod
    def validate_local_url(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    @property
    def is_local(self) -> bool:
        if self.provider == ProviderName.MOCK:
            return True
        if self.provider not in {ProviderName.OLLAMA, ProviderName.OPENAI_COMPATIBLE}:
            return False
        if not self.base_url:
            return self.provider == ProviderName.OLLAMA
        hostname = (urlparse(self.base_url).hostname or "").casefold()
        return hostname in {"localhost", "127.0.0.1", "::1"}

    @classmethod
    def from_env(cls) -> "LLMSettings":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        provider = ProviderName(os.getenv("LLM_PROVIDER", "ollama").lower())
        privacy_raw = "local_only" if os.getenv("LOCAL_ONLY", "false").lower() == "true" else os.getenv("EXECUTION_MODE", "auto").lower()
        stage_models = {
            stage: value
            for stage in ("discovery", "semantic", "extraction", "planner", "vision", "insight", "report", "presentation")
            if (value := os.getenv(f"LLM_{stage.upper()}_MODEL", ""))
        }
        key = os.getenv("LLM_API_KEY") or os.getenv(f"{provider.value.upper()}_API_KEY")
        return cls(
            provider=provider,
            model=os.getenv("LLM_MODEL", ""),
            api_key=SecretStr(key) if key else None,
            base_url=os.getenv("LLM_BASE_URL") or None,
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            privacy_mode=PrivacyMode(privacy_raw),
            stage_models=stage_models,
            discovery_workers=int(os.getenv("LLM_DISCOVERY_WORKERS", "3")),
        )

    def model_for(self, stage: str) -> str:
        return self.stage_models.get(stage, self.model)
