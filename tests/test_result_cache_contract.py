"""A code update must not return a previously completed, incorrectly typed result."""

from types import SimpleNamespace

from adaptive_document_agent.models import DocumentProfile, ParsedDocument, PipelineResult
from adaptive_document_agent.services.llm.config import LLMSettings
from adaptive_document_agent.ui import app
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_streamlit_auto_flow import _Streamlit


def test_new_output_contract_rebuilds_result_without_clearing_other_caches(tmp_path, monkeypatch):
    settings = LLMSettings(model="test")
    cache = DiskCache(tmp_path)
    old_key = app._analysis_scope_key(b"pdf", "", settings)
    old_result = PipelineResult(document=ParsedDocument(document_id="test", sha256="hash",
                               safe_filename="input.pdf", page_count=1), profile=DocumentProfile())
    cache.set_model(f"analysis-result-{old_key}", old_result)
    old_stage_versions = app.ANALYSIS_VERSION, app.EXTRACTION_VERSION
    monkeypatch.setattr(app, "PIPELINE_VERSION", "updated-unit-and-label-contract")
    new_key = app._analysis_scope_key(b"pdf", "", settings)
    assert new_key != old_key
    assert (app.ANALYSIS_VERSION, app.EXTRACTION_VERSION) == old_stage_versions
    current = old_result.model_copy(update={"pipeline_version": app.PIPELINE_VERSION})
    calls = []
    monkeypatch.setattr(app, "create_llm_client", lambda settings: object())
    monkeypatch.setattr(app, "LLMGateway", lambda *args, **kwargs: object())

    def rebuild(*args, **kwargs):
        calls.append(True)
        return current

    monkeypatch.setattr(app, "DocumentOrchestrator", lambda *args, **kwargs: SimpleNamespace(analyse_pdf=rebuild))
    st = _Streamlit()
    options = dict(scope_key=new_key, analysis_focus="", settings=settings, cache=cache)
    assert app._analyse_upload(st, b"pdf", **options) is current
    assert app._analyse_upload(st, b"pdf", **options) is current
    assert calls == [True]
    assert cache.get_model(f"analysis-result-{old_key}", PipelineResult) == old_result
