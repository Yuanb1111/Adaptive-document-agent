"""Provider-specific model picker and live catalog regressions."""

from contextlib import nullcontext

from pydantic import SecretStr

from adaptive_document_agent.services.llm import LLMSettings, ProviderName
from adaptive_document_agent.services.llm.model_catalog import (
    _models_from_payload,
    list_provider_models,
    recommended_models,
)
from adaptive_document_agent.ui.sidebar import render_sidebar


def test_deepseek_is_the_application_default():
    settings = LLMSettings()
    assert settings.provider == ProviderName.DEEPSEEK
    assert settings.model == "deepseek-flash"
    assert recommended_models(ProviderName.DEEPSEEK)[:2] == ["deepseek-flash", "deepseek-v4-pro"]


def test_openai_recommendations_use_current_gpt6_model_ids():
    assert recommended_models(ProviderName.OPENAI)[:3] == [
        "gpt-6-sol",
        "gpt-6-astra",
        "gpt-6-luna",
    ]


def test_live_catalog_filters_non_generation_models():
    openai = _models_from_payload(
        ProviderName.OPENAI,
        {"data": [{"id": "gpt-6-sol"}, {"id": "text-embedding-3-small"}, {"id": "gpt-realtime"}]},
    )
    gemini = _models_from_payload(
        ProviderName.GEMINI,
        {
            "models": [
                {
                    "name": "models/gemini-new-flash",
                    "baseModelId": "gemini-new-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-embedding-001",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        },
    )
    assert openai == ["gpt-6-sol"]
    assert gemini == ["gemini-new-flash"]


def test_deepseek_live_models_are_loaded_from_models_endpoint(monkeypatch):
    captured = {}

    def fake_request(url, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return {"data": [{"id": "deepseek-v4-pro"}, {"id": "deepseek-flash"}]}

    monkeypatch.setattr(
        "adaptive_document_agent.services.llm.model_catalog._request_json",
        fake_request,
    )
    models = list_provider_models(ProviderName.DEEPSEEK, api_key="secret")
    assert models == ["deepseek-flash", "deepseek-v4-pro"]
    assert captured["url"] == "https://api.deepseek.com/models"
    assert captured["headers"]["Authorization"] == "Bearer secret"


class SidebarUI:
    sidebar = nullcontext()

    def __init__(self, provider: str):
        self.provider = provider
        self.session_state = {}
        self.model_options = []
        self.stage_options = {}

    def selectbox(self, label, options, **kwargs):
        if label == "Execution Mode":
            return "Auto"
        if label == "Provider":
            return self.provider
        if label == "Model":
            self.model_options = list(options)
            return options[0]
        if label.endswith(" model"):
            self.stage_options[label] = list(options)
            return options[0]
        return options[0]

    def text_input(self, label, value="", **kwargs):
        return value

    def button(self, *args, **kwargs):
        return False

    def expander(self, *args, **kwargs):
        return nullcontext()

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def test_provider_selection_immediately_changes_model_options(monkeypatch):
    defaults = LLMSettings(
        provider=ProviderName.DEEPSEEK,
        model="deepseek-flash",
        api_key=SecretStr("configured-but-not-sent-without-refresh"),
    )
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)

    deepseek_ui = SidebarUI("DeepSeek")
    assert render_sidebar(deepseek_ui, public_deployment=False).model == "deepseek-flash"
    assert deepseek_ui.model_options[:2] == ["deepseek-flash", "deepseek-v4-pro"]
    assert deepseek_ui.stage_options["Planner model"] == [
        "Use main model",
        "deepseek-flash",
        "deepseek-v4-pro",
    ]

    openai_ui = SidebarUI("OpenAI")
    assert render_sidebar(openai_ui, public_deployment=False).model == "gpt-6-sol"
    assert openai_ui.model_options[:3] == ["gpt-6-sol", "gpt-6-astra", "gpt-6-luna"]
    assert openai_ui.stage_options["Planner model"][:4] == [
        "Use main model",
        "gpt-6-sol",
        "gpt-6-astra",
        "gpt-6-luna",
    ]

    gemini_ui = SidebarUI("Gemini")
    assert render_sidebar(gemini_ui, public_deployment=False).model == "gemini-3.8-flash"
    assert gemini_ui.model_options[0].startswith("gemini-")
