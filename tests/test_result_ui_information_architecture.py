"""Regressions for compact, ordered result pages and top-level downloads."""

from contextlib import nullcontext
import inspect

from adaptive_document_agent.models import (
    DocumentProfile,
    ParsedDocument,
    PipelineResult,
    ReportPlan,
    ValidationIssue,
)
from adaptive_document_agent.services.qa_reporter import QAItem, QAReport
from adaptive_document_agent.ui import analysis, app, overview, quality


def _result() -> PipelineResult:
    return PipelineResult(
        document=ParsedDocument(
            document_id="ui-test",
            sha256="abc",
            safe_filename="source.pdf",
            page_count=17,
        ),
        profile=DocumentProfile(
            document_type="Prospectus",
            document_purpose="Explain the offering.",
            important_sections=["Business", "Financials"],
            data_quality_notes=["First note", "Second note", "First note"],
        ),
        report_plan=ReportPlan(title="Report"),
    )


class UI:
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.markdown_values = []
        self.expanders = []

    def columns(self, count):
        return [self] * count

    def metric(self, *args, **kwargs):
        return None

    def warning(self, value):
        self.warnings.append(value)

    def error(self, value):
        self.errors.append(value)

    def markdown(self, value):
        self.markdown_values.append(value)

    def expander(self, label, **kwargs):
        self.expanders.append((label, kwargs.get("expanded", False)))
        return nullcontext()

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def test_downloads_render_before_long_result_tabs():
    source = inspect.getsource(app.run_app)
    assert source.index("deliverables.render") < source.index("st.tabs")
    assert "Exports & Deliverables" not in source


def test_overview_aggregates_repeated_quality_notes_into_one_alert():
    ui = UI()
    overview.render(ui, _result())
    assert len(ui.warnings) == 1
    assert "2 data-quality note(s)" in ui.warnings[0]
    assert ui.expanders == [("Data-quality notes", False)]
    assert ui.markdown_values.count("- First note") == 1


def test_quality_groups_many_issues_instead_of_one_alert_per_issue(monkeypatch):
    result = _result()
    result.validation_warnings = [
        ValidationIssue(code="w1", message="Warning one", stage="extract"),
        ValidationIssue(code="w2", message="Warning two", stage="report"),
        ValidationIssue(code="e1", message="Error one", stage="export", severity="error"),
    ]
    report = QAReport(
        document_title="Report",
        critical_errors=[QAItem(code="block", severity="CRITICAL", message="Blocked")],
        is_export_blocked=True,
    )
    monkeypatch.setattr(
        "adaptive_document_agent.services.qa_reporter.run_comprehensive_qa",
        lambda _result: report,
    )
    ui = UI()
    quality.render(ui, result)
    assert len(ui.errors) == 1
    assert len(ui.warnings) == 1
    labels = [label for label, _ in ui.expanders]
    assert labels == [
        "Critical blockers",
        "Validation errors (1)",
        "Validation warnings (2)",
        "Document limitations (2)",
    ]


def test_analysis_sections_are_numbered_and_collapsed_after_first():
    intro, sections = analysis.split_markdown_sections(
        "# Report\n\nIntro\n\n## Summary\n\nOne\n\n## Risks\n\nTwo"
    )
    assert intro == "# Report\n\nIntro"
    assert sections == [("Summary", "One"), ("Risks", "Two")]

    result = _result()
    result.report_markdown = "# Report\n\nIntro\n\n## Summary\n\nOne\n\n## Risks\n\nTwo"
    ui = UI()
    analysis.render(ui, result)
    assert ui.expanders == [("1. Summary", True), ("2. Risks", False)]
