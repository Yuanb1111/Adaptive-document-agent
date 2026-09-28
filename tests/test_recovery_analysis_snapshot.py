"""The recovery pass must replace every artifact derived from stale evidence."""

import pytest

from adaptive_document_agent.agent import orchestrator, output_planning
from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.models import (
    DocumentPage, DocumentProfile, Observation, ParsedDocument, PresentationTopic,
    PresentationTopicSelection, SourceEvidence, ValidationIssue, ValidationReport,
)


def revenue(identifier, year, value):
    return Observation(
        id=identifier, metric_original="Revenue", value=value, raw_value=str(value),
        period=str(year), unit="currency", currency="USD", confidence=.95,
        evidence=[SourceEvidence(page=1, text=f"Revenue {year}: USD {value}",
                                 extraction_method="digital_text", confidence=.95)],
    )


@pytest.mark.parametrize("recovery_mode", ["new", "unchanged", "conflict"])
def test_recovery_refreshes_analysis_validation_insights_topics_and_report(monkeypatch, recovery_mode):
    document = ParsedDocument(
        document_id="test", sha256="test", safe_filename="test.pdf", page_count=2,
        pages=[DocumentPage(page_number=1, text="Revenue"), DocumentPage(page_number=2, text="Outside scope")],
    )
    profile = DocumentProfile(metrics=["Revenue"], analysis_page_ranges=[(1, 1)])
    initial = [revenue("a", 2020, 100), revenue("b", 2022, 121)]
    added = revenue("c", 2024 if recovery_mode == "new" else 2022, 146.41)
    recovered = initial if recovery_mode == "unchanged" else [*initial, added]
    extraction_passes = iter([initial, recovered])
    monkeypatch.setattr(orchestrator.DocumentOrchestrator, "_load_document", lambda *args: document)
    monkeypatch.setattr(orchestrator.DocumentDiscovery, "discover", lambda *args, **kwargs: profile)
    monkeypatch.setattr(orchestrator.TableExtractor, "extract", lambda *args, **kwargs: {})
    monkeypatch.setattr(orchestrator.ObservationExtractor, "extract", lambda *args, **kwargs: next(extraction_passes))
    recovery_pages = []
    monkeypatch.setattr(BorderlessTableExtractor, "extract", lambda self, page, number: recovery_pages.append(number) or [])

    validation_snapshots, topic_snapshots, chart_snapshots, report_snapshots = [], [], [], []
    validate = orchestrator.CalculationValidator.validate
    def track_validation(self, results):
        validation_snapshots.append([r.model_copy(deep=True) for r in results])
        return validate(self, results)
    monkeypatch.setattr(orchestrator.CalculationValidator, "validate", track_validation)

    planning = output_planning.plan_outputs
    def track_topics(gateway, result, **kwargs):
        topic_snapshots.append(result.model_copy(deep=True))
        report, _, _ = planning(gateway, result, **kwargs)
        directory, _ = series_directory(result)
        selection = PresentationTopicSelection(topics=[PresentationTopic(
            id="revenue", title="Revenue", question="How did revenue change?", rationale="Reported series",
            series_ids=[directory[0]["id"]],
        )] if directory else [])
        return report, selection, None
    monkeypatch.setattr(output_planning, "plan_outputs", track_topics)

    def track_charts(self, plan, results, index, **kwargs):
        chart_snapshots.append([[o.id for o in group] for group in kwargs["requested_series"]])
        return []  # Exercise report refresh even when the final output has no chart.
    monkeypatch.setattr(orchestrator.ChartPlanner, "plan", track_charts)

    render = orchestrator.ReportGenerator.generate
    def track_report(self, profile, report_plan, insights, issues, **kwargs):
        markdown = render(self, profile, report_plan, insights, issues, **kwargs)
        report_snapshots.append(markdown)
        return markdown
    monkeypatch.setattr(orchestrator.ReportGenerator, "generate", track_report)

    def track_report_validation(self, markdown, results):
        assert markdown == report_snapshots[-1]
        return ValidationReport(issues=[ValidationIssue(
            code=f"report_pass_{len(report_snapshots)}", message="Reviewed current snapshot", stage="report",
        )])
    monkeypatch.setattr(orchestrator.ReportValidator, "validate", track_report_validation)

    result = orchestrator.DocumentOrchestrator().analyse_pdf(b"synthetic")
    count = 1 if recovery_mode == "unchanged" else 2
    assert len(validation_snapshots) == len(topic_snapshots) == len(report_snapshots) == count
    assert result.insights == topic_snapshots[-1].insights
    assert result.analysis_results == validation_snapshots[-1]
    assert result.report_markdown == report_snapshots[-1]
    assert result.presentation_topics is not None
    assert recovery_pages == [1]
    codes = {issue.code for issue in result.validation_warnings}
    assert f"report_pass_{count}" in codes
    if count == 2:
        assert "report_pass_1" not in codes
    if recovery_mode == "new":
        assert {o.id for o in result.observations} == {"a", "b", "c"}
        assert chart_snapshots[-1] == [["a", "b", "c"]]
        assert chart_snapshots[0] == [["a", "b"]]
        change_task = next(t.id for t in result.analysis_plan if t.analysis_type == "absolute_change")
        change = next(r for r in result.analysis_results if r.task_id == change_task)
        assert change.result == pytest.approx(46.41)
        insight = next(i for i in result.insights if change_task in i.result_ids)
        assert "46.41" in insight.narrative
        assert "46.41" in result.report_markdown
    elif recovery_mode == "conflict":
        assert "conflicting_values" in codes
        assert result.insights == []  # Old, now-contradicted conclusions cannot survive.
        assert all(r.result is None for r in result.analysis_results)
