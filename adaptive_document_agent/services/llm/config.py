"""Environment-backed provider and privacy settings."""

import os
from enum import StrEnum
from urllib.parse import urlparse
from typing import Literal

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
    provider: ProviderName = ProviderName.DEEPSEEK
    model: str = "deepseek-flash"
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=120.0, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    privacy_mode: PrivacyMode = PrivacyMode.AUTO
    stage_models: dict[str, str] = Field(default_factory=dict)
    discovery_workers: int = Field(default=4, ge=1, le=4)
    discovery_chunk_tokens: int = Field(default=12000, ge=2000, le=24000)
    semantic_batch_size: int = Field(default=96, ge=24, le=128)
    discovery_thinking: Literal["disabled", "enabled", "provider_default"] = "disabled"
    simple_task_reasoning: Literal["reduced", "provider_default"] = "reduced"
    # A range avoids guessing the provider's holiday / peak-time billing band.
    deepseek_price_band: Literal["range", "peak", "off_peak"] = "range"

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
        provider = ProviderName(os.getenv("LLM_PROVIDER", "deepseek").lower())
        privacy_raw = "local_only" if os.getenv("LOCAL_ONLY", "false").lower() == "true" else os.getenv("EXECUTION_MODE", "auto").lower()
        stage_models = {
            stage: value
            for stage in ("discovery", "semantic", "extraction", "planner", "vision", "insight", "report", "presentation")
            if (value := os.getenv(f"LLM_{stage.upper()}_MODEL", ""))
        }
        key = os.getenv("LLM_API_KEY") or os.getenv(f"{provider.value.upper()}_API_KEY")
        return cls(
            provider=provider,
            model=os.getenv("LLM_MODEL", "deepseek-flash" if provider == ProviderName.DEEPSEEK else ""),
            api_key=SecretStr(key) if key else None,
            base_url=os.getenv("LLM_BASE_URL") or None,
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            privacy_mode=PrivacyMode(privacy_raw),
            stage_models=stage_models,
            discovery_workers=int(os.getenv("LLM_DISCOVERY_WORKERS", "4")),
            discovery_chunk_tokens=int(os.getenv("LLM_DISCOVERY_CHUNK_TOKENS", "12000")),
            semantic_batch_size=int(os.getenv("LLM_SEMANTIC_BATCH_SIZE", "96")),
            discovery_thinking=os.getenv("LLM_DISCOVERY_THINKING", "disabled"),
            simple_task_reasoning=os.getenv("LLM_SIMPLE_TASK_REASONING", "reduced"),
            deepseek_price_band=os.getenv("LLM_DEEPSEEK_PRICE_BAND", "range"),
        )

    def model_for(self, stage: str) -> str:
        return self.stage_models.get(stage, self.model)
