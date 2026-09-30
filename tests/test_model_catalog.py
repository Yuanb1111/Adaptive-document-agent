"""Provider-specific model picker and live catalog regressions."""

from contextlib import nullcontext

from pydantic import SecretStr

from adaptive_document_agent.services.llm import LLMSettings, ProviderName
from adaptive_document_agent.services.llm.model_catalog import (
    _models_from_payload,
    ModelCatalogError,
    list_provider_models,
    recommended_models,
    shortlist_models,
)
from adaptive_document_agent.ui.sidebar import _available_models, render_sidebar


def test_deepseek_is_the_application_default():
    settings = LLMSettings()
    assert settings.provider == ProviderName.DEEPSEEK
    assert settings.model == "deepseek-flash"
    assert recommended_models(ProviderName.DEEPSEEK)[:2] == ["deepseek-flash", "deepseek-v4-pro"]


def test_openai_recommendations_use_current_gpt6_model_ids():
    assert recommended_models(ProviderName.OPENAI)[:3] == [
        "gpt-6.1-sol",
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
    assert models == ["deepseek-v4-pro", "deepseek-flash"]
    assert captured["url"] == "https://api.deepseek.com/models"
    assert captured["headers"]["Authorization"] == "Bearer secret"


class SidebarUI:
    sidebar = nullcontext()

    def container(self):
        return nullcontext()

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
    assert render_sidebar(openai_ui, public_deployment=False).model == "gpt-6.1-sol"
    assert openai_ui.model_options[:3] == ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna"]
    assert openai_ui.stage_options["Planner model"][:4] == [
        "Use main model",
        "gpt-6.1-sol",
        "gpt-6-astra",
        "gpt-6-luna",
    ]

    gemini_ui = SidebarUI("Gemini")
    assert render_sidebar(gemini_ui, public_deployment=False).model == "gemini-3.8-flash"
    assert gemini_ui.model_options[0].startswith("gemini-")


def test_openai_shortlist_keeps_latest_version_per_tier_and_hides_snapshots():
    models = [
        "gpt-4o", "gpt-6-sol", "gpt-6.1-sol-2026-09-30", "gpt-6-astra",
        "gpt-6.1-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.3-codex",
        "gpt-6.1-sol-2026-09-29", "ft:gpt-4o:custom",
    ]
    assert shortlist_models(ProviderName.OPENAI, models) == [
        "gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna",
    ]
    # A future version replaces only its own tier without a code update.
    assert shortlist_models(ProviderName.OPENAI, [*models, "gpt-6.10-sol"])[0] == "gpt-6.10-sol"


def test_shortlist_never_invents_unavailable_aliases_or_pads_with_old_models():
    assert shortlist_models(ProviderName.OPENAI, ["gpt-6.1-sol-2026-09-30", "gpt-4o"]) == [
        "gpt-6.1-sol-2026-09-30",
    ]
    assert shortlist_models(ProviderName.OPENAI, ["gpt-6-sol-2026-09-30", "gpt-6-sol-2026-09-29"]) == [
        "gpt-6-sol-2026-09-30",
    ]


def test_catalog_orders_by_creation_and_prefers_canonical_aliases_in_shortlist():
    models = _models_from_payload(ProviderName.OPENAI_COMPATIBLE, {"data": [
        {"id": "old", "created": 1},
        {"id": "recent-2026-09-30", "created": 50},
        {"id": "recent", "created": 20},
        {"id": "second", "created": 15},
        {"id": "third", "created": 10},
        {"id": "embedding-model", "created": 100},
    ]})
    assert shortlist_models(ProviderName.OPENAI_COMPATIBLE, models) == ["recent", "second", "third"]


def test_gemini_catalog_uses_numeric_versions_when_timestamps_are_absent():
    models = _models_from_payload(ProviderName.GEMINI, {"models": [
        {"baseModelId": name} for name in (
            "gemini-1.5-pro", "gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.7-flash",
        )
    ]})
    assert shortlist_models(ProviderName.GEMINI, models) == [
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.1-pro-preview",
    ]


def test_refresh_shortlists_live_models_and_cache_survives_reruns(monkeypatch):
    ui = SidebarUI("OpenAI")
    calls = []

    def catalog(*args, **kwargs):
        calls.append(kwargs)
        return ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-astra", "gpt-6-luna", "gpt-4o"]

    monkeypatch.setattr("adaptive_document_agent.ui.sidebar.list_provider_models", catalog)
    kwargs = dict(api_key="test-only", base_url=None, auto_discover=False)
    expected = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna"]
    assert _available_models(ui, ProviderName.OPENAI, refresh=True, **kwargs) == (expected, None)
    assert _available_models(ui, ProviderName.OPENAI, refresh=False, **kwargs) == (expected, None)
    assert len(calls) == 1
    _available_models(ui, ProviderName.OPENAI, refresh=True, **kwargs)
    assert len(calls) == 2


def test_failed_refresh_uses_compact_recommendations(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ModelCatalogError("Unavailable")

    monkeypatch.setattr("adaptive_document_agent.ui.sidebar.list_provider_models", unavailable)
    models, error = _available_models(
        SidebarUI("OpenAI"), ProviderName.OPENAI,
        api_key="test-only", base_url=None, auto_discover=False, refresh=True,
    )
    assert len(models) == 3
    assert models[0] == "gpt-6.1-sol"
    assert error == "Unavailable"


def test_refresh_retains_current_main_and_stage_choices_within_limit(monkeypatch):
    defaults = LLMSettings(provider=ProviderName.OPENAI, model="gpt-6-sol")
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)
    monkeypatch.setattr("adaptive_document_agent.ui.sidebar.list_provider_models", lambda *a, **kw: [
        "gpt-6.1-sol", "gpt-6-sol", "gpt-6-astra", "gpt-6-luna", "gpt-4o",
    ])

    class RefreshUI(SidebarUI):
        def button(self, *args, **kwargs):
            return True

        def selectbox(self, label, options, **kwargs):
            selected = super().selectbox(label, options, **kwargs)
            return selected if label in {"Provider", "Execution Mode"} else options[kwargs.get("index", 0)]

    ui = RefreshUI("OpenAI")
    ui.session_state.update(model_select_openai="gpt-4o", stage_model_openai_discovery="gpt-6-luna")
    settings = render_sidebar(ui, public_deployment=False)
    assert settings.model == "gpt-4o"
    assert settings.stage_models == {"discovery": "gpt-6-luna"}
    assert len(ui.model_options) == 4  # Three actual IDs and manual entry.
    assert all(len(options) <= 4 for options in ui.stage_options.values())


def test_manual_model_is_available_to_stages_and_main_model_clears_override(monkeypatch):
    defaults = LLMSettings(
        provider=ProviderName.OPENAI, model="gpt-6.1-sol",
        stage_models={"discovery": "gpt-6-luna"},
    )
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)

    class ManualUI(SidebarUI):
        def selectbox(self, label, options, **kwargs):
            selected = super().selectbox(label, options, **kwargs)
            if label == "Model":
                return options[-1]
            return selected if label in {"Provider", "Execution Mode"} else options[kwargs.get("index", 0)]

        def text_input(self, label, value="", **kwargs):
            return "gpt-4o" if label == "Custom model ID" else value

    ui = ManualUI("OpenAI")
    assert render_sidebar(ui, public_deployment=False).stage_models == {"discovery": "gpt-6-luna"}
    ui.session_state["stage_model_openai_discovery"] = "Use main model"
    settings = render_sidebar(ui, public_deployment=False)
    assert settings.model == "gpt-4o"
    assert settings.stage_models == {}
    assert "gpt-4o" in ui.stage_options["Discovery model"]
