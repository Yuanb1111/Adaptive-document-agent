"""Real-widget checks for branded results and blocked exports; no live model calls."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from adaptive_document_agent.models import (
    DocumentProfile, Insight, ParsedDocument, PipelineResult, PresentationPlan,
    ReportPlan, SourceEvidence,
)
from adaptive_document_agent.services.qa_reporter import CriticalQAError
from adaptive_document_agent.ui import app, branding, deliverables


def sample_result():
    return PipelineResult(
        document=ParsedDocument(document_id="ui", sha256="ui", safe_filename="source <script>.pdf", page_count=17),
        profile=DocumentProfile(document_type="Prospectus", document_summary="A source-grounded summary.",
                                document_summary_pages=[2, 4], detected_time_periods=["2024", "2025"]),
        insights=[Insight(id="i1", title="A reported finding", narrative='<script>alert("source")</script>',
                          kind="reported_fact", evidence=[SourceEvidence(page=4, text="Original source wording.",
                          extraction_method="text", confidence=.9)])],
        report_plan=ReportPlan(title="Document review"),
        report_markdown="# Document review\n\n## Findings\n\nEvidence on page 4.",
        presentation_plan=PresentationPlan(title="Document review", planning_origin="model", editorial_status="ready"),
    )


def test_document_strings_are_escaped_in_custom_cards():
    ui = Mock()
    result = sample_result()
    branding.result_heading(ui, result)
    branding.insight_card(ui, result.insights[0], 1)
    html = "\n".join(call.args[0] for call in ui.markdown.call_args_list)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Source pages: 4" in html


@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("native_findings", [False, True])
def test_result_widgets_keep_downloads_evidence_and_export_gate(monkeypatch, blocked, native_findings):
    import streamlit as st
    from adaptive_document_agent.services import export_readiness, presentation_editorial
    from adaptive_document_agent.utils import timing

    result = sample_result()
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "true")
    # AppTest shares this pytest process. Production logging setup changes
    # propagation, which would otherwise steal later tests' caplog records.
    monkeypatch.setattr(timing, "configure_timing_logging", lambda: None)
    monkeypatch.setattr(export_readiness, "check_export_readiness", lambda _: {"ready": True, "backend": "test"})
    monkeypatch.setattr(presentation_editorial, "review_presentation", lambda *args: [])
    monkeypatch.setattr(app, "_analyse_upload", lambda *args, **kwargs: result)
    monkeypatch.setattr(app, "_analysis_scope_key", lambda *args: "widget-test-scope")
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: None if kwargs.get("key") else BytesIO(b"test"))
    report = SimpleNamespace(cache_hit=False, status="passed", attempts=1, coverage=[], issues=[], to_dict=lambda: {})
    from adaptive_document_agent.services.ppt_preflight import PreflightIssue
    from adaptive_document_agent.services.presentation_preflight_report import PreflightQAError, PreflightReport
    native = PreflightReport([PreflightIssue(1, "native_finding", "Native finding detail", "error" if blocked else "warning")]) if native_findings else None

    def export(*args, **kwargs):
        if blocked:
            if native:
                raise PreflightQAError(native)
            raise CriticalQAError("Synthetic QA blocker")
        return SimpleNamespace(payload=b"verified-test-payload", report=report,
                               timings_ms={"ppt_export_total": 123}, build_cache_hit=False, preflight_report=native)

    monkeypatch.setattr(deliverables, "export_pptx_with_report", export)
    from adaptive_document_agent.ui import completion_notification
    notifications = []
    failures = []
    reviews = []
    def notify(ui, verified, *, needs_review=False):
        notifications.append(verified.payload)
        reviews.append(needs_review)
    monkeypatch.setattr(completion_notification, "notify_export_ready", notify)
    monkeypatch.setattr(completion_notification, 'notify_outcome', lambda ui, outcome, **kwargs: failures.append(outcome))
    page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
    assert not page.exception, page.exception
    assert [tab.label for tab in page.tabs] == ["Overview", "Analysis", "Charts", "Extracted Data", "Sources", "Data Quality", "Technical Details"]
    assert any("Summary source pages: 2, 4" in item.value for item in page.caption)
    assert any("Source pages: 4" in item.value for item in page.markdown)
    assert not any(item.value == "Original source wording." for item in page.text)
    downloads = [item.proto.label for item in page.get("download_button")]
    assert "Download Markdown" in downloads and "Download CSV" in downloads
    progress = "\n".join(item.value for item in page.markdown)
    if native_findings:
        assert "Download preflight QA report" in downloads
        assert any("Native preflight:" in item.value for item in page.caption)
        assert any("Native finding detail" in item.value for item in page.markdown)
    if blocked:
        assert failures == ['export_blocked']
        assert notifications == []
        assert "Download presentation (.pptx)" not in downloads
        assert any(item.label == "Download presentation (.pptx)" and item.disabled for item in page.button)
        assert 'aria-valuenow="100"' not in progress
    else:
        assert not failures
        assert reviews == [native_findings]
        assert notifications == [b"verified-test-payload"]
        assert "Download presentation (.pptx)" in downloads
        assert 'aria-valuenow="100"' in progress
        # A deliberate export click creates a cycle; ordinary reruns retain it.
        next(item for item in page.button if item.label == "Regenerate PowerPoint only").click().run()
        assert not page.exception, page.exception
        export_runs = page.session_state["ppt_notification_export_runs"]
        first_cycle = next(iter(export_runs.values()))["id"]
        page.run()
        assert not page.exception, page.exception
        assert next(iter(page.session_state["ppt_notification_export_runs"].values()))["id"] == first_cycle
        next(item for item in page.button if item.label == "Regenerate PowerPoint only").click().run()
        assert not page.exception, page.exception
        assert next(iter(page.session_state["ppt_notification_export_runs"].values()))["id"] != first_cycle
    # Selecting Sources loads only that view while keeping downloads available.
    # Use the widget key directly; AppTest's state wrapper varies by version.
    page.session_state["result_view_widget-test-scope"] = "Sources"
    page.run()
    assert not page.exception, page.exception
    assert any(item.value == "Original source wording." for item in page.text)
    assert all(item.proto.ignore_rerun for item in page.get("download_button"))
