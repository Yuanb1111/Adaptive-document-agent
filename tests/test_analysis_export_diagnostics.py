"""Analysis downloads carry the current failed export snapshot without stale state."""

from contextlib import nullcontext
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adaptive_document_agent.models import DocumentProfile, ParsedDocument, PipelineResult, ReportPlan
from adaptive_document_agent.services.export import export_json
from adaptive_document_agent.services import export_diagnostics as diagnostics
from adaptive_document_agent.services.ppt_preflight import PreflightIssue
from adaptive_document_agent.services.presentation_preflight_report import PreflightQAError, PreflightReport
from adaptive_document_agent.services.presentation_visual_qa import VisualIssue, VisualQAError, VisualQAReport
from adaptive_document_agent.services.qa_reporter import CriticalQAError, QAItem, QAReport
from adaptive_document_agent.ui import completion_notification, deliverables


def _result():
    return PipelineResult(
        document=ParsedDocument(document_id="doc", sha256="abc", safe_filename="source.pdf", page_count=1),
        profile=DocumentProfile(),
        report_plan=ReportPlan(title="Report"),
        report_markdown="# Report",
    )


class DownloadUI:
    def __init__(self):
        self.session_state = {}
        self.downloads = {}
        self.download_options = {}

    def columns(self, count, **kwargs):
        return [nullcontext() for _ in range(count if isinstance(count, int) else len(count))]

    def download_button(self, label, data, filename, *args, **kwargs):
        self.downloads[filename] = data
        self.download_options[filename] = kwargs

    def container(self, **kwargs):
        return nullcontext()

    def expander(self, *args, **kwargs):
        return nullcontext()

    def spinner(self, *args, **kwargs):
        return nullcontext()

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _failure(stage):
    financial = QAReport(document_title="Report")
    if stage == "financial":
        financial.critical_errors = [QAItem(
            code="chart_topic_mismatch", severity="CRITICAL", slide_id="topic_output",
            related_ids=["chart_output"], message="Chart does not match its retained topic.",
        )]
        return CriticalQAError("Evidence check blocked", financial_report=financial), "chart_topic_mismatch"
    if stage == "preflight":
        report = PreflightReport([PreflightIssue(2, "visual_block_overlap", "Source table overlaps a chart", "error")])
        error = PreflightQAError(report)
        error.financial_report = financial
        return error, "visual_block_overlap"
    if stage == "rendering":
        report = VisualQAReport(issues=[VisualIssue(3, "RENDERING_BLOCKED", "critical", message="Missing renderer")])
        error = VisualQAError(report)
        error.financial_report = financial
        return error, "RENDERING_BLOCKED"
    return CriticalQAError("Native build failed", financial_report=financial), "EXPORT_FAILED"


@pytest.mark.parametrize("stage", ["financial", "preflight", "rendering", "generation"])
def test_downloaded_analysis_contains_the_same_current_failure_as_qa_report(monkeypatch, stage):
    result, ui, progress = _result(), DownloadUI(), Mock()
    error, code = _failure(stage)
    monkeypatch.setattr("adaptive_document_agent.services.presentation_editorial.review_presentation", lambda *args: [])
    monkeypatch.setattr(deliverables, "export_pptx_with_report", Mock(side_effect=error))
    snapshot = Mock(wraps=diagnostics.export_diagnostics)
    monkeypatch.setattr(diagnostics, "export_diagnostics", snapshot)
    before = result.model_dump()

    deliverables.render(ui, result, b"source PDF", progress)

    embedded = json.loads(ui.downloads["analysis_data.json"])["pptx_export_diagnostics"]
    standalone = json.loads(ui.downloads["qa_report.json"])
    assert embedded == standalone
    assert embedded["export_error"]["stage"] == stage
    assert any(item["code"] == code for item in embedded["critical_errors"])
    assert embedded["is_export_blocked"] is True
    assert snapshot.call_count == 1
    assert result.model_dump() == before
    progress.fail.assert_called_once_with("PowerPoint export blocked")
    progress.finish.assert_not_called()
    assert all(options.get("on_click") == "ignore" for options in ui.download_options.values())


def test_successful_retry_does_not_export_previous_failure_or_modify_analysis_state(monkeypatch):
    result, ui, progress = _result(), DownloadUI(), Mock()
    error, _ = _failure("financial")
    verified = SimpleNamespace(
        payload=b"verified PowerPoint", report=VisualQAReport(),
        timings_ms={"ppt_export_total": 12}, preflight_report=None, build_cache_hit=False,
    )
    monkeypatch.setattr("adaptive_document_agent.services.presentation_editorial.review_presentation", lambda *args: [])
    monkeypatch.setattr(deliverables, "export_pptx_with_report", Mock(side_effect=[error, verified]))
    monkeypatch.setattr(completion_notification, "notify_export_ready", Mock())
    def finish_after_downloads():
        assert {"analysis_presentation.pptx", "analysis_report.md", "extracted_observations.csv",
                "analysis_data.json"} <= ui.downloads.keys()
    progress.finish.side_effect = finish_after_downloads
    deliverables.render(ui, result, b"source PDF", progress)
    assert json.loads(ui.downloads["analysis_data.json"])["pptx_export_diagnostics"]["is_export_blocked"]
    ui.downloads.clear()

    deliverables.render(ui, result, b"source PDF", progress)

    exported = json.loads(ui.downloads["analysis_data.json"])
    assert "pptx_export_diagnostics" not in exported
    assert "qa_report.json" not in ui.downloads
    assert ui.downloads["analysis_presentation.pptx"] == verified.payload
    assert exported["export_timings_ms"] == verified.timings_ms
    assert not hasattr(result, "pptx_export_diagnostics")
    progress.finish.assert_called_once()
    assert all(options.get("on_click") == "ignore" for options in ui.download_options.values())


def test_generic_exception_diagnostics_keep_existing_redaction(monkeypatch):
    result, ui = _result(), DownloadUI()
    monkeypatch.setattr("adaptive_document_agent.services.presentation_editorial.review_presentation", lambda *args: [])
    monkeypatch.setattr(deliverables, "export_pptx_with_report", Mock(side_effect=RuntimeError("secret content and private path")))
    monkeypatch.setattr(diagnostics, "run_comprehensive_qa", lambda *args, **kwargs: QAReport(document_title="Report"))

    deliverables.render(ui, result, b"source PDF", Mock())

    embedded = json.loads(ui.downloads["analysis_data.json"])["pptx_export_diagnostics"]
    assert embedded["export_error"]["stage"] == "generation"
    assert "RuntimeError" in embedded["export_error"]["message"]
    assert "secret content" not in json.dumps(embedded)
    assert "private path" not in json.dumps(embedded)


def test_optional_json_diagnostics_do_not_change_default_contract_or_result():
    result = _result()
    before = result.model_dump()
    diagnostic = {"export_error": {"stage": "financial"}, "critical_errors": [{"code": "chart_topic_mismatch"}]}
    embedded = json.loads(export_json(result, pptx_export_diagnostics=diagnostic))
    assert embedded["pptx_export_diagnostics"] == diagnostic
    assert result.model_dump() == before
    assert "pptx_export_diagnostics" not in json.loads(export_json(result))
