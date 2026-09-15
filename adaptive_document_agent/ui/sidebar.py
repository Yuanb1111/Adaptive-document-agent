"""In-memory provider and privacy controls."""

from pydantic import SecretStr

from adaptive_document_agent.services.llm import LLMSettings, PrivacyMode, ProviderName


def render_sidebar(st) -> LLMSettings:
    defaults = LLMSettings.from_env()
    provider_labels = ["OpenAI", "DeepSeek", "Gemini", "OpenRouter", "Ollama", "Custom OpenAI-Compatible"]
    provider_by_label = {
        "OpenAI": ProviderName.OPENAI,
        "DeepSeek": ProviderName.DEEPSEEK,
        "Gemini": ProviderName.GEMINI,
        "OpenRouter": ProviderName.OPENROUTER,
        "Ollama": ProviderName.OLLAMA,
        "Custom OpenAI-Compatible": ProviderName.OPENAI_COMPATIBLE,
    }
    label_by_provider = {value: key for key, value in provider_by_label.items()}
    mode_labels = ["Auto", "Cloud", "Local Only"]
    default_mode = {
        PrivacyMode.AUTO: "Auto",
        PrivacyMode.CLOUD: "Cloud",
        PrivacyMode.LOCAL_ONLY: "Local Only",
    }[defaults.privacy_mode]
    with st.sidebar:
        st.header("Model Settings")
        mode_label = st.selectbox("Execution Mode", mode_labels, index=mode_labels.index(default_mode))
        default_provider_label = label_by_provider.get(defaults.provider, "Ollama")
        provider_label = st.selectbox("Provider", provider_labels, index=provider_labels.index(default_provider_label))
        provider = provider_by_label[provider_label]
        model = st.text_input(
            "Model",
            value=defaults.model if provider == defaults.provider else "",
            help="Example: gpt-5.6-terra, deepseek-flash, gemini-2.5-flash, or llama3.1",
        )
        default_url = defaults.base_url if provider == defaults.provider else ("http://localhost:11434" if provider == ProviderName.OLLAMA else "")
        base_url = st.text_input("Base URL (optional)", value=default_url)
        default_key = defaults.api_key.get_secret_value() if defaults.api_key and provider == defaults.provider else ""
        key = st.text_input("API key", value=default_key, type="password", help="Loaded from .env when configured; never written to reports or exports.")
        privacy = {"Auto": PrivacyMode.AUTO, "Cloud": PrivacyMode.CLOUD, "Local Only": PrivacyMode.LOCAL_ONLY}[mode_label]
        settings = LLMSettings(provider=provider, model=model, base_url=base_url or None, api_key=SecretStr(key) if key else None, privacy_mode=privacy)
        if settings.is_local:
            st.success("🖥 Local model")
            if privacy == PrivacyMode.LOCAL_ONLY:
                st.caption("LLM processing remains on a loopback local endpoint. No cloud fallback is allowed.")
        else:
            st.warning("☁ Cloud model")
            st.caption("Relevant document content is sent to the configured provider.")
        return settings
