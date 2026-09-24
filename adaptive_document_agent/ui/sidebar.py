"""In-memory provider and privacy controls."""

from collections.abc import MutableMapping
from hashlib import sha256
import time

from pydantic import SecretStr

from adaptive_document_agent.services.llm import LLMSettings, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.model_catalog import (
    ModelCatalogError,
    list_provider_models,
    recommended_models,
)

from .deployment import is_public_deployment


_MANUAL_MODEL = "Enter a model ID manually…"
_CATALOG_TTL_SECONDS = 300


def _session_state(st) -> MutableMapping:
    state = getattr(st, "session_state", None)
    return state if isinstance(state, MutableMapping) else {}


def _available_models(
    st,
    provider: ProviderName,
    *,
    api_key: str | None,
    base_url: str | None,
    refresh: bool,
    auto_discover: bool,
) -> tuple[list[str], str | None]:
    """Merge stable suggestions with a short-lived, session-only live catalog."""
    suggestions = recommended_models(provider)
    if not (refresh or auto_discover):
        return suggestions, None

    state = _session_state(st)
    cache = state.setdefault("provider_model_catalog", {})
    key_fingerprint = sha256((api_key or "").encode()).hexdigest()[:12]
    cache_key = f"{provider.value}|{base_url or ''}|{key_fingerprint}"
    cached = cache.get(cache_key) if isinstance(cache, dict) else None
    now = time.monotonic()
    if not refresh and cached and now - cached["loaded_at"] < _CATALOG_TTL_SECONDS:
        live = cached["models"]
    else:
        try:
            live = list_provider_models(provider, api_key=api_key, base_url=base_url)
        except ModelCatalogError as exc:
            return suggestions, str(exc)
        if isinstance(cache, dict):
            cache[cache_key] = {"loaded_at": now, "models": live}

    return list(dict.fromkeys([*suggestions, *live])), None


def render_sidebar(st, *, public_deployment: bool | None = None) -> LLMSettings:
    public_deployment = is_public_deployment() if public_deployment is None else public_deployment
    defaults = LLMSettings.from_env()
    provider_by_label = {
        "DeepSeek": ProviderName.DEEPSEEK,
        "OpenAI": ProviderName.OPENAI,
        "Gemini": ProviderName.GEMINI,
        "OpenRouter": ProviderName.OPENROUTER,
        "Ollama": ProviderName.OLLAMA,
        "Custom OpenAI-Compatible": ProviderName.OPENAI_COMPATIBLE,
    }
    provider_labels = (
        ["DeepSeek", "OpenAI", "Gemini", "OpenRouter"]
        if public_deployment
        else list(provider_by_label)
    )
    label_by_provider = {value: key for key, value in provider_by_label.items()}
    mode_labels = ["Cloud"] if public_deployment else ["Auto", "Cloud", "Local Only"]
    default_mode = "Cloud" if public_deployment else {
        PrivacyMode.AUTO: "Auto",
        PrivacyMode.CLOUD: "Cloud",
        PrivacyMode.LOCAL_ONLY: "Local Only",
    }[defaults.privacy_mode]
    with st.sidebar:
        st.header("Model Settings")
        if public_deployment:
            st.info("Public hosted mode: use your own cloud-provider API key.")
        mode_label = st.selectbox("Execution Mode", mode_labels, index=mode_labels.index(default_mode))
        default_provider_label = label_by_provider.get(defaults.provider, "DeepSeek")
        if default_provider_label not in provider_labels:
            default_provider_label = "DeepSeek"
        provider_label = st.selectbox("Provider", provider_labels, index=provider_labels.index(default_provider_label))
        provider = provider_by_label[provider_label]
        default_url = defaults.base_url if provider == defaults.provider else ("http://localhost:11434" if provider == ProviderName.OLLAMA else "")
        base_url = st.text_input("Base URL (optional)", value=default_url)
        key = st.text_input(
            "API key",
            value="",
            type="password",
            help="Used only for this session; never written to disk, logs, reports, or exports.",
        )
        st.caption("Enter your own API key. It is kept only in the current session and must be entered again later.")
        configured_key = defaults.api_key.get_secret_value() if defaults.api_key and not public_deployment else None
        effective_key = key or configured_key
        refresh_models = bool(
            st.button(
                "Refresh available models",
                key=f"refresh_models_{provider.value}",
                help="Reload the provider's live catalog. New provider models then appear without a code update.",
                use_container_width=True,
            )
        )
        auto_discover = bool(key) or provider == ProviderName.OLLAMA or (
            provider == ProviderName.OPENAI_COMPATIBLE and bool(base_url)
        )
        models, catalog_error = _available_models(
            st,
            provider,
            api_key=effective_key,
            base_url=base_url or None,
            refresh=refresh_models,
            auto_discover=auto_discover,
        )
        preferred_model = defaults.model if provider == defaults.provider else (models[0] if models else "")
        if preferred_model and preferred_model not in models:
            models.insert(0, preferred_model)
        options = [*models, _MANUAL_MODEL]
        selected_model = st.selectbox(
            "Model",
            options,
            index=options.index(preferred_model) if preferred_model in options else 0,
            key=f"model_select_{provider.value}",
            help="Provider-specific models. Enter an API key or refresh to load the live catalog.",
        )
        if selected_model == _MANUAL_MODEL:
            model = st.text_input(
                "Custom model ID",
                value=preferred_model if preferred_model not in models else "",
                key=f"custom_model_{provider.value}",
                help="Use the exact model ID accepted by the selected provider.",
            ).strip()
        else:
            model = selected_model
        if catalog_error:
            st.caption(f"Live catalog unavailable: {catalog_error} Showing recommended models and manual entry.")
        elif auto_discover or refresh_models:
            st.caption(f"Live catalog loaded: {len(models)} compatible model(s). Cached for 5 minutes.")
        else:
            st.caption("Showing recommended models. Enter an API key or refresh to query the live provider catalog.")
        privacy = {"Auto": PrivacyMode.AUTO, "Cloud": PrivacyMode.CLOUD, "Local Only": PrivacyMode.LOCAL_ONLY}[mode_label]
        api_key = SecretStr(key) if key else (None if public_deployment else defaults.api_key)
        stage_models = {}
        with st.expander("Stage models (optional)"):
            st.caption(
                f"Each stage uses {provider_label}. Choose the main model or another model "
                "from this provider; cross-provider routing is not allowed."
            )
            stage_options = ["Use main model", *models]
            for stage in ("discovery", "semantic", "extraction", "planner", "vision", "insight", "report", "presentation"):
                configured_stage_model = (
                    defaults.stage_models.get(stage, "") if provider == defaults.provider else ""
                )
                selected_stage_model = st.selectbox(
                    f"{stage.title()} model",
                    stage_options,
                    index=(
                        stage_options.index(configured_stage_model)
                        if configured_stage_model in stage_options
                        else 0
                    ),
                    key=f"stage_model_{provider.value}_{stage}",
                )
                if selected_stage_model in models:
                    stage_models[stage] = selected_stage_model
        settings = LLMSettings(
            provider=provider,
            model=model,
            base_url=base_url or None,
            api_key=api_key,
            privacy_mode=privacy,
            discovery_workers=defaults.discovery_workers,
            stage_models=stage_models,
            timeout_seconds=defaults.timeout_seconds,
            temperature=defaults.temperature,
        )
        if settings.is_local:
            st.success("🖥 Local model")
            if privacy == PrivacyMode.LOCAL_ONLY:
                st.caption("LLM processing remains on a loopback local endpoint. No cloud fallback is allowed.")
        else:
            st.warning("☁ Cloud model")
            st.caption("Relevant document content is sent to the configured provider.")
        return settings
