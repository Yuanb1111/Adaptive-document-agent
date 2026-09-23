"""An uploaded PDF starts analysis once without a scope-confirmation gate."""

from types import SimpleNamespace

from adaptive_document_agent.ui import app as ui_app


class _Status:
    def __init__(self) -> None:
        self.messages = []

    def write(self, message: str) -> None:
        self.messages.append(message)

    def update(self, **kwargs) -> None:
        self.messages.append(kwargs["label"])


class _Streamlit:
    def __init__(self) -> None:
        self.session_state = {}
        self.errors = []
        self.statuses = []

    def status(self, label: str, *, expanded: bool) -> _Status:
        status = _Status()
        self.statuses.append((label, expanded, status))
        return status

    def error(self, message: str) -> None:
        self.errors.append(message)


def test_upload_auto_analysis_reuses_result_and_manual_scope_can_override(monkeypatch) -> None:
    st = _Streamlit()
    calls = []
    result = object()
    settings = SimpleNamespace(model="configured-model")
    cache = SimpleNamespace(get_model=lambda *args: None, set_model=lambda *args: None)

    class Orchestrator:
        def __init__(self, gateway, *, cache) -> None:
            assert cache is not None

        def analyse_pdf(self, raw_pdf, *, progress, analysis_focus, scope):
            calls.append((raw_pdf, analysis_focus, scope))
            progress("Discovering document scope")
            return result

    monkeypatch.setattr(ui_app, "DocumentOrchestrator", Orchestrator)
    monkeypatch.setattr(ui_app, "create_llm_client", lambda settings: "client")
    monkeypatch.setattr(ui_app, "LLMGateway", lambda client, settings, **kwargs: "gateway")
    kwargs = dict(scope_key="pdf-and-settings", analysis_focus="financial performance",
                  settings=settings, cache=cache)

    assert ui_app._analyse_upload(st, b"%PDF", **kwargs) is result
    assert calls == [(b"%PDF", "financial performance", None)]
    assert ui_app._analyse_upload(st, b"%PDF", **kwargs) is result
    assert len(calls) == 1
    assert len(st.statuses) == 1

    manual_scope = object()
    assert ui_app._analyse_upload(st, b"%PDF", **kwargs, scope=manual_scope, force=True) is result
    assert calls[-1] == (b"%PDF", "financial performance", manual_scope)
    assert len(calls) == 2
    assert not st.errors


def test_upload_with_no_configured_model_does_not_start_analysis() -> None:
    st = _Streamlit()
    result = ui_app._analyse_upload(
        st, b"%PDF", scope_key="pdf", analysis_focus="", cache=None,
        settings=SimpleNamespace(model=""),
    )
    assert result is None
    assert st.errors == ["Configure a model before analysis."]
    assert not st.statuses
