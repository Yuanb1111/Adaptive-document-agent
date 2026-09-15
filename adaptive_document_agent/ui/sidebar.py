"""In-memory provider and privacy controls."""

from pydantic import SecretStr

from adaptive_document_agent.services.llm import LLMSettings, PrivacyMode, ProviderName

from .deployment import is_public_deployment


def render_sidebar(st, *, public_deployment: bool | None = None) -> LLMSettings:
    public_deployment = is_public_deployment() if public_deployment is None else public_deployment
    defaults = LLMSettings.from_env()
    provider_by_label = {
        "OpenAI": ProviderName.OPENAI,
        "DeepSeek": ProviderName.DEEPSEEK,
        "Gemini": ProviderName.GEMINI,
        "OpenRouter": ProviderName.OPENROUTER,
        "Ollama": ProviderName.OLLAMA,
        "Custom OpenAI-Compatible": ProviderName.OPENAI_COMPATIBLE,
    }
    provider_labels = (
        ["OpenAI", "DeepSeek", "Gemini", "OpenRouter"]
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
        default_provider_label = label_by_provider.get(defaults.provider, "OpenAI")
        if default_provider_label not in provider_labels:
            default_provider_label = "OpenAI"
        provider_label = st.selectbox("Provider", provider_labels, index=provider_labels.index(default_provider_label))
        provider = provider_by_label[provider_label]
        model = st.text_input(
            "Model",
            value=defaults.model if provider == defaults.provider else "",
            help="Example: gpt-5.6-terra, deepseek-flash, gemini-2.5-flash, or llama3.1",
        )
        default_url = defaults.base_url if provider == defaults.provider else ("http://localhost:11434" if provider == ProviderName.OLLAMA else "")
        base_url = st.text_input("Base URL (optional)", value=default_url)
        key = st.text_input(
            "API key",
            value="",
            type="password",
            help="Used only for this session; never written to disk, logs, reports, or exports.",
        )
        st.caption("Enter your own API key. It is kept only in the current session and must be entered again later.")
        privacy = {"Auto": PrivacyMode.AUTO, "Cloud": PrivacyMode.CLOUD, "Local Only": PrivacyMode.LOCAL_ONLY}[mode_label]
        api_key = SecretStr(key) if key else (None if public_deployment else defaults.api_key)
        settings = LLMSettings(
            provider=provider,
            model=model,
            base_url=base_url or None,
            api_key=api_key,
            privacy_mode=privacy,
        )
        if settings.is_local:
            st.success("🖥 Local model")
            if privacy == PrivacyMode.LOCAL_ONLY:
                st.caption("LLM processing remains on a loopback local endpoint. No cloud fallback is allowed.")
        else:
            st.warning("☁ Cloud model")
            st.caption("Relevant document content is sent to the configured provider.")
        return settings
