"""Executable credential-boundary regressions; fake keys and offline spies only."""

import json
from contextlib import nullcontext
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest

from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.credentials import configured_credential, credential_scope
from adaptive_document_agent.services.llm.exceptions import LLMConfigurationError
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.ui.sidebar import render_sidebar
from tests.test_model_catalog import SidebarUI

DUMMY = "dummy-source-credential-not-a-real-key"
SECOND = "dummy-destination-credential-not-a-real-key"
CLOUD = [ProviderName.DEEPSEEK, ProviderName.OPENAI, ProviderName.GEMINI, ProviderName.OPENROUTER]
LABELS = {
    ProviderName.DEEPSEEK: "DeepSeek", ProviderName.OPENAI: "OpenAI", ProviderName.GEMINI: "Gemini",
    ProviderName.OPENROUTER: "OpenRouter", ProviderName.OLLAMA: "Ollama",
    ProviderName.OPENAI_COMPATIBLE: "Custom OpenAI-Compatible",
}


@pytest.fixture
def catalog(monkeypatch):
    calls = []

    def request(url, headers, timeout):
        calls.append((url, headers))
        return {"data": [{"id": "test-model"}], "models": [{"name": "test-model"}]}

    monkeypatch.setattr("adaptive_document_agent.services.llm.model_catalog._request_json", request)
    return calls


@pytest.fixture
def completion(monkeypatch):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="ok"), finish_reason="stop")], usage={})

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=complete))
    monkeypatch.setattr(LiteLLMProvider, "_request_client", lambda self: nullcontext({}))
    return calls


def select(at, label, value):
    next(widget for widget in at.selectbox if widget.label == label).select(value).run()
    assert not at.exception


def enter(at, label, value):
    next(widget for widget in at.text_input if widget.label == label).input(value).run()
    assert not at.exception


def app(public):
    return AppTest.from_string(f'''import streamlit as st
from adaptive_document_agent.ui.sidebar import render_sidebar
st.session_state['result'] = render_sidebar(st, public_deployment={public!r})
''').run()


@pytest.mark.parametrize("source", list(LABELS))
@pytest.mark.parametrize("destination", list(LABELS))
def test_default_key_fallback_requires_same_provider(source, destination, monkeypatch, catalog):
    defaults = LLMSettings(provider=source, model="test-model", api_key=SecretStr(DUMMY))
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)
    settings = render_sidebar(SidebarUI(LABELS[destination]), public_deployment=False)
    assert bool(settings.api_key) == (source == destination)
    if settings.api_key:
        assert settings.api_key.get_secret_value() == DUMMY


@pytest.mark.parametrize("provider", list(LABELS))
@pytest.mark.parametrize("url", [None, "https://one.invalid/v1", "https://two.invalid/v1"])
def test_configured_key_requires_same_endpoint_and_nonpublic_mode(provider, url):
    defaults = LLMSettings(provider=provider, api_key=SecretStr(DUMMY), base_url="https://one.invalid/v1/")
    assert configured_credential(defaults, provider, url, public_deployment=False) == (
        DUMMY if url == "https://one.invalid/v1" else None)
    assert configured_credential(defaults, provider, url, public_deployment=True) is None


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("source,destination", [(a, b) for a in CLOUD for b in CLOUD if a != b])
def test_real_streamlit_provider_switch_clears_manual_key(public, source, destination, monkeypatch, catalog, completion):
    monkeypatch.setattr(LLMSettings, "from_env", lambda: LLMSettings(provider=source, model="test-model"))
    at = app(public)
    enter(at, "API key", DUMMY)
    assert at.session_state["result"].api_key.get_secret_value() == DUMMY
    before = len(catalog)
    select(at, "Provider", LABELS[destination])
    settings = at.session_state["result"]
    assert settings.api_key is None
    assert next(w for w in at.text_input if w.label == "API key").value == ""
    assert len(catalog) == before  # No auto-discovery with the prior key.
    with pytest.raises(LLMConfigurationError, match="API key is required"):
        LLMGateway(LiteLLMProvider(settings), settings).generate_text([], stage="discovery")
    assert completion == []
    # The destination's own key is valid; a plain rerun preserves it.
    enter(at, "API key", SECOND)
    at.run()
    settings = at.session_state["result"]
    LLMGateway(LiteLLMProvider(settings), settings).generate_text([], stage="discovery")
    assert completion[-1]["api_key"] == SECOND
    assert completion[-1]["custom_llm_provider"] == destination.value
    assert DUMMY not in json.dumps(catalog[before:])


@pytest.mark.parametrize("url", ["https://two.invalid/v1", "https://one.invalid/v2", "http://one.invalid/v1", "https://one.invalid:8443/v1"])
@pytest.mark.parametrize("manual", [False, True])
def test_real_streamlit_endpoint_changes_do_not_reuse_key(url, manual, monkeypatch, catalog, completion):
    defaults = LLMSettings(provider=ProviderName.OPENAI_COMPATIBLE, model="test-model",
                           base_url="https://one.invalid/v1", api_key=None if manual else SecretStr(DUMMY))
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)
    at = app(False)
    if manual:
        enter(at, "API key", DUMMY)
    assert at.session_state["result"].api_key.get_secret_value() == DUMMY
    before = len(catalog)
    enter(at, "Base URL", url)
    settings = at.session_state["result"]
    assert settings.api_key is None
    assert DUMMY not in json.dumps(catalog[before:])
    LLMGateway(LiteLLMProvider(settings), settings).generate_text([], stage="discovery")
    assert completion[-1]["api_key"] == "no-api-key"
    assert completion[-1]["api_base"] == url


@pytest.mark.parametrize("provider", CLOUD)
def test_configured_proxy_endpoint_is_preserved_for_catalog_and_generation(provider, monkeypatch, catalog, completion):
    defaults = LLMSettings(provider=provider, model="test-model", api_key=SecretStr(DUMMY), base_url="https://proxy.invalid/v1")
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)

    class Refresh(SidebarUI):
        def button(self, *args, **kwargs):
            return True

    settings = render_sidebar(Refresh(LABELS[provider]), public_deployment=False)
    assert settings.base_url == defaults.base_url
    assert catalog[-1][0].startswith(defaults.base_url + "/")
    LLMGateway(LiteLLMProvider(settings), settings).generate_text([], stage="discovery")
    assert completion[-1]["api_base"] == defaults.base_url
    assert completion[-1]["api_key"] == DUMMY


@pytest.mark.parametrize("provider", CLOUD)
def test_public_sessions_ignore_server_keys_and_endpoint_overrides(provider, monkeypatch, catalog):
    defaults = LLMSettings(provider=provider, model="test-model", api_key=SecretStr(DUMMY), base_url="https://server-only.invalid/v1")
    monkeypatch.setattr(LLMSettings, "from_env", lambda: defaults)
    first = app(True)
    enter(first, "API key", SECOND)
    second = app(True)
    assert second.session_state["result"].api_key is None
    assert second.session_state["result"].base_url is None
    assert first.session_state["result"].api_key.get_secret_value() == SECOND
    assert DUMMY not in json.dumps(catalog)
    assert "server-only.invalid" not in json.dumps(catalog)


def test_scope_has_no_key_or_raw_endpoint_and_normalizes_trailing_slash():
    scope = credential_scope(ProviderName.OPENAI_COMPATIBLE, "https://one.invalid/v1/")
    assert scope == credential_scope(ProviderName.OPENAI_COMPATIBLE, "https://one.invalid/v1")
    assert "one.invalid" not in scope and len(scope) == 64


@pytest.mark.parametrize("provider", list(LABELS))
@pytest.mark.parametrize("model", ["test-model", "gemini/test-model", "openai/test-model", "organization/model"])
def test_main_and_stage_models_cannot_reroute_keys(provider, model, completion):
    settings = LLMSettings(provider=provider, model=model, api_key=SecretStr(DUMMY),
                           base_url="https://chosen.invalid/v1", stage_models={"discovery": model})
    gateway = LLMGateway(LiteLLMProvider(settings), settings)
    gateway.generate_text([], stage="discovery")
    gateway.generate_text([], stage="report")
    route = "openai" if provider == ProviderName.OPENAI_COMPATIBLE else provider.value
    assert all(c["custom_llm_provider"] == route and c["model"].startswith(route + "/") for c in completion)
    assert all(c["api_base"] == settings.base_url and c["api_key"] == DUMMY for c in completion)
    assert DUMMY not in json.dumps(gateway.usage)


@pytest.mark.parametrize("provider", CLOUD)
def test_missing_key_never_reaches_sdk(provider, completion):
    with pytest.raises(LLMConfigurationError, match="API key is required"):
        LiteLLMProvider(LLMSettings(provider=provider, model="test-model")).generate_text([], model="test-model")
    assert completion == []


def test_custom_endpoint_must_be_explicit(completion):
    with pytest.raises(LLMConfigurationError, match="base URL is required"):
        LiteLLMProvider(LLMSettings(provider=ProviderName.OPENAI_COMPATIBLE, model="test-model")).generate_text([])
    assert completion == []


def test_actual_litellm_transport_never_inherits_other_provider_key_or_endpoint(monkeypatch):
    # Import/use the real adapter in a scrubbed environment. HTTP is intercepted;
    # no real credentials, profiles, external API requests, or model costs load.
    import os
    import socket
    import httpx

    requests = []

    def send(self, request, **kwargs):
        requests.append(request)
        return httpx.Response(200, request=request, json={
            "id": "fake", "model": "test-model", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    def no_network(*args, **kwargs):
        raise AssertionError("Unmocked network access is forbidden")

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    with patch.dict(os.environ, {"OPENAI_API_KEY": DUMMY, "OPENAI_API_BASE": "https://ambient.invalid/v1",
                               "LITELLM_LOCAL_MODEL_COST_MAP": "True", "DO_NOT_TRACK": "True"}, clear=True):
        settings = LLMSettings(provider=ProviderName.OPENAI_COMPATIBLE, model="organization/model", base_url="https://custom.invalid/v1")
        assert LiteLLMProvider(settings).generate_text([]).text == "ok"
        assert requests[-1].url.host == "custom.invalid"
        assert requests[-1].headers["authorization"] == "Bearer no-api-key"
        settings = LLMSettings(provider=ProviderName.OPENAI, model="gemini/test-model", api_key=SecretStr(SECOND))
        assert LiteLLMProvider(settings).generate_text([]).text == "ok"
        assert requests[-1].url.host == "api.openai.com"
        assert requests[-1].headers["authorization"] == "Bearer " + SECOND
        assert json.loads(requests[-1].content)["model"] == "gemini/test-model"


@pytest.mark.parametrize("model,version", [("gemini-2.5-flash", "v1beta"), ("gemini-3.8-flash", "v1alpha")])
def test_actual_gemini_transport_preserves_versioned_default_and_custom_endpoint(model, version, monkeypatch):
    import os
    import socket
    import httpx

    requests = []

    def send(self, request, **kwargs):
        requests.append(request)
        return httpx.Response(200, request=request, json={"candidates": [{"index": 0,
            "content": {"parts": [{"text": "ok"}], "role": "model"}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}})

    def no_network(*args, **kwargs):
        raise AssertionError("Unmocked network access is forbidden")

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    with patch.dict(os.environ, {"GEMINI_API_BASE": "https://ambient.invalid/v1", "GEMINI_API_KEY": DUMMY,
                               "LITELLM_LOCAL_MODEL_COST_MAP": "True", "DO_NOT_TRACK": "True"}, clear=True):
        for base in (None, "https://chosen.invalid/v1beta"):
            settings = LLMSettings(provider=ProviderName.GEMINI, model=model, api_key=SecretStr(SECOND), base_url=base)
            assert LiteLLMProvider(settings).generate_text([{"role": "user", "content": "synthetic probe"}]).text == "ok"
            request = requests[-1]
            assert request.url.host == ("chosen.invalid" if base else "generativelanguage.googleapis.com")
            assert request.url.path == f"/{'v1beta' if base else version}/models/{model}:generateContent"
            assert request.headers["x-goog-api-key"] == SECOND
            assert DUMMY not in str(request.url) and SECOND not in str(request.url)


@pytest.mark.parametrize("name", ["Authorization", "x-goog-api-key"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_catalog_redirects_cannot_forward_credentials(name, status, monkeypatch):
    import io
    from email.message import Message
    from urllib.request import HTTPSHandler, ProxyHandler, build_opener
    from urllib.response import addinfourl
    from adaptive_document_agent.services.llm import model_catalog

    class Spy(HTTPSHandler):
        def __init__(self):
            super().__init__()
            self.requests = []

        def https_open(self, request):
            self.requests.append(request)
            headers = Message()
            headers["Location"] = "https://different-provider.invalid/catalog"
            response = addinfourl(io.BytesIO(b"{}"), headers, request.full_url, status)
            response.msg = "Redirect"
            return response

    spy = Spy()
    monkeypatch.setattr(model_catalog, "build_opener", lambda handler: build_opener(ProxyHandler({}), spy, handler))
    with pytest.raises(model_catalog.ModelCatalogError) as failure:
        model_catalog._request_json("https://selected-provider.invalid/catalog", {name: DUMMY}, 1)
    assert len(spy.requests) == 1
    assert DUMMY not in str(failure.value)


def test_actual_gemini_redirect_cannot_forward_key(monkeypatch, capsys):
    import os
    import socket
    import httpx
    from adaptive_document_agent.services.llm.exceptions import LLMTransportError

    requests = []

    def send(self, request):
        requests.append(request)
        return httpx.Response(307, request=request, headers={"Location": "https://different-provider.invalid/generate"}, content=b"{}")

    def no_network(*args, **kwargs):
        raise AssertionError("Unmocked network access is forbidden")

    monkeypatch.setattr(httpx.Client, "_send_single_request", send)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    with patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True", "DO_NOT_TRACK": "True"}, clear=True):
        settings = LLMSettings(provider=ProviderName.GEMINI, model="gemini-2.5-flash", api_key=SecretStr(DUMMY))
        gateway = LLMGateway(LiteLLMProvider(settings), settings)
        with pytest.raises(LLMTransportError) as failure:
            gateway.generate_text([{"role": "user", "content": "synthetic probe"}], stage="discovery")
        assert 1 <= len(requests) <= 2  # Existing bounded retry stays at the original host.
        assert all(request.url.host == "generativelanguage.googleapis.com" for request in requests)
        assert DUMMY not in str(failure.value)
        assert DUMMY not in json.dumps(gateway.usage)

    captured = capsys.readouterr()
    assert DUMMY not in captured.out + captured.err
