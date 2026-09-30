"""In-memory provider and privacy controls."""

from collections.abc import MutableMapping
from hashlib import sha256
import time

from pydantic import SecretStr

from adaptive_document_agent.services.llm import LLMSettings, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.credentials import configured_credential, credential_scope
from adaptive_document_agent.services.llm.model_catalog import (
    ModelCatalogError,
    list_provider_models,
    recommended_models,
    shortlist_models,
)

from .deployment import is_public_deployment
from .branding import sidebar_brand


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
    """Shortlist a session-only live catalog, falling back to recommendations."""
    suggestions = shortlist_models(provider, recommended_models(provider))

    state = _session_state(st)
    cache = state.setdefault("provider_model_catalog", {})
    key_fingerprint = sha256((api_key or "").encode()).hexdigest()[:12]
    cache_key = f"{provider.value}|{base_url or ''}|{key_fingerprint}"
    cached = cache.get(cache_key) if isinstance(cache, dict) else None
    if not (refresh or auto_discover) and not cached:
        return suggestions, None
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

    return shortlist_models(provider, live), None


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
        sidebar_brand(st)
        st.header("Model connection")
        mode_label = "Cloud" if public_deployment else st.selectbox(
            "Execution Mode", mode_labels, index=mode_labels.index(default_mode),
        )
        default_provider_label = label_by_provider.get(defaults.provider, "DeepSeek")
        if default_provider_label not in provider_labels:
            default_provider_label = "DeepSeek"
        provider_label = st.selectbox("Provider", provider_labels, index=provider_labels.index(default_provider_label))
        provider = provider_by_label[provider_label]
        # Reserve the model's visual position before collecting credentials
        # needed to discover its options during this same Streamlit rerun.
        model_controls = st.container()
        default_url = defaults.base_url if provider == defaults.provider else ("http://localhost:11434" if provider == ProviderName.OLLAMA else "")
        base_url = (default_url or None) if not public_deployment else None
        if provider in {ProviderName.OLLAMA, ProviderName.OPENAI_COMPATIBLE}:
            with st.expander("Connection settings"):
                base_url = st.text_input("Base URL", value=default_url or "", key=f"base_url_{provider.value}")
        key = st.text_input(
            "API key",
            value="",
            type="password",
            key=f"api_key_{credential_scope(provider, base_url)}",
            help="Used only for this session; never written to disk, logs, reports, or exports.",
        )
        configured_key = configured_credential(
            defaults, provider, base_url, public_deployment=public_deployment,
        )
        effective_key = key or configured_key
        advanced_controls = st.expander("Advanced model settings", expanded=False)
        with advanced_controls:
            refresh_models = bool(st.button(
                "Refresh available models",
                key=f"refresh_models_{provider.value}",
                help="Refresh up to three recent models. Other models can be entered manually.",
                use_container_width=True,
            ))
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
        model_key = f"model_select_{provider.value}"
        current_model = _session_state(st).get(model_key)
        if isinstance(current_model, str) and current_model != _MANUAL_MODEL:
            preferred_model = current_model
        if preferred_model and preferred_model not in models:
            models = [preferred_model, *models][:3]
        options = [*models, _MANUAL_MODEL]
        with model_controls:
            selected_model = st.selectbox(
                "Model",
                options,
                index=options.index(preferred_model) if preferred_model in options else 0,
                key=model_key,
                help="Up to three recent models; your configured selection is retained. Use manual entry for other IDs.",
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
        privacy = {"Auto": PrivacyMode.AUTO, "Cloud": PrivacyMode.CLOUD, "Local Only": PrivacyMode.LOCAL_ONLY}[mode_label]
        api_key = SecretStr(effective_key) if effective_key else None
        stage_models = {}
        with advanced_controls:
            if catalog_error:
                st.caption(f"Live catalog unavailable: {catalog_error} Showing recommended models and manual entry.")
            elif auto_discover or refresh_models:
                st.caption(f"Showing {len(models)} model(s), up to 3 recent choices. Current selection retained. Cached for 5 minutes.")
            else:
                st.caption("Showing up to 3 model choices. Enter an API key or refresh to update the provider catalog.")
            st.caption(
                f"Each stage uses {provider_label}. Choose the main model or another model "
                "from this provider; cross-provider routing is not allowed."
            )
            for stage in ("discovery", "semantic", "extraction", "planner", "vision", "insight", "report", "presentation"):
                configured_stage_model = (
                    defaults.stage_models.get(stage, "") if provider == defaults.provider else ""
                )
                stage_key = f"stage_model_{provider.value}_{stage}"
                current_stage_model = _session_state(st).get(stage_key)
                if isinstance(current_stage_model, str):
                    configured_stage_model = "" if current_stage_model == "Use main model" else current_stage_model
                stage_models_available = list(dict.fromkeys([model, *models]))[:3] if model else models
                if configured_stage_model and configured_stage_model not in stage_models_available:
                    stage_models_available = [configured_stage_model, *stage_models_available]
                stage_options = ["Use main model", *stage_models_available[:3]]
                selected_stage_model = st.selectbox(
                    f"{stage.title()} model",
                    stage_options,
                    index=(
                        stage_options.index(configured_stage_model)
                        if configured_stage_model in stage_options
                        else 0
                    ),
                    key=stage_key,
                )
                if selected_stage_model in stage_options and selected_stage_model != "Use main model":
                    stage_models[stage] = selected_stage_model
        settings = LLMSettings(
            provider=provider,
            model=model,
            base_url=base_url or None,
            api_key=api_key,
            privacy_mode=privacy,
            discovery_workers=defaults.discovery_workers,
            discovery_chunk_tokens=defaults.discovery_chunk_tokens,
            semantic_batch_size=defaults.semantic_batch_size,
            discovery_thinking=defaults.discovery_thinking,
            deepseek_price_band=defaults.deepseek_price_band,
            stage_models=stage_models,
            timeout_seconds=defaults.timeout_seconds,
            temperature=defaults.temperature,
        )
        if settings.is_local:
            st.success("Local model")
            if privacy == PrivacyMode.LOCAL_ONLY:
                st.caption("LLM processing remains on a loopback local endpoint. No cloud fallback is allowed.")
        else:
            st.caption(f"Cloud processing · Relevant document content is sent to {provider_label}.")
        return settings
