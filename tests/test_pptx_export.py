"""PowerPoint export remains editable and presentation-ready."""

import io
import zipfile

from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE

from adaptive_document_agent.models import (
    ChartPlan,
    DocumentProfile,
    Insight,
    Observation,
    ParsedDocument,
    PipelineResult,
    ReportPlan,
    SourceEvidence,
    ValidationIssue,
)
from adaptive_document_agent.services.export import export_pptx


def _result() -> PipelineResult:
    evidence = SourceEvidence(page=234, text="267,025", table_id="income", extraction_method="digital_table", confidence=0.9)
    observations = [
        Observation(
            id=f"revenue-{year}",
            metric_original="Revenue",
            value=value,
            raw_value=f"{value / 1_000:,.0f}",
            unit="currency",
            raw_unit="RMB in thousands",
            unit_scale=1_000,
            currency="CNY",
            period=f"FY{year}",
            dimensions={"period_basis": "FY", "table_context": "RESULTS OF OPERATIONS"},
            evidence=[evidence],
            confidence=0.9,
        )
        for year, value in ((2023, 267_025_000), (2024, 325_257_000), (2025, 521_747_000))
    ]
    return PipelineResult(
        document=ParsedDocument(document_id="doc", sha256="abc", safe_filename="prospectus.pdf", page_count=300),
        profile=DocumentProfile(
            document_type="Prospectus",
            document_purpose="Review historical financial performance for investor assessment.",
            metrics=["Revenue"],
            analysis_page_ranges=[(227, 263)],
            analysis_focus="Financial information",
            data_quality_notes=["Values use RMB in thousands in the source table."],
        ),
        observations=observations,
        insights=[
            Insight(
                id="insight-1",
                title="Revenue increased across the reported period",
                narrative="Revenue rose from RMB267.0 million in 2023 to RMB521.7 million in 2025.",
                kind="reported_fact",
                importance=0.9,
                confidence=0.9,
                evidence=[evidence],
            )
        ],
        report_plan=ReportPlan(title="Financial information analysis"),
        charts=[
            ChartPlan(
                id="chart-1",
                title="Revenue — Reported Values",
                chart_type="line",
                available_chart_types=["line", "bar", "area", "table"],
                question="How did revenue change across the reported years?",
                observation_ids=[item.id for item in observations],
                source_pages=[234],
                x_metric="revenue",
                y_metric="revenue",
                x_axis_title="Period",
                y_axis_title="Revenue (CNY)",
            )
        ],
        validation_warnings=[ValidationIssue(code="source_scale", message="Source values are reported in RMB thousands.", stage="report")],
    )


def test_pptx_export_contains_editable_chart_and_table() -> None:
    payload = export_pptx(_result())

    assert payload.startswith(b"PK")
    deck = Presentation(io.BytesIO(payload))
    assert len(deck.slides) == 6
    assert any(shape.has_chart for slide in deck.slides for shape in slide.shapes)
    assert any(shape.has_table for slide in deck.slides for shape in slide.shapes)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert any(name.startswith("ppt/charts/chart") for name in names)
        assert any(name.startswith("ppt/embeddings/") for name in names)
        chart_xml = b"".join(archive.read(name) for name in names if name.startswith("ppt/charts/chart"))
        assert b'axId val="-' not in chart_xml
        assert b'crossAx val="-' not in chart_xml


def test_pptx_export_skips_constant_period_chart() -> None:
    result = _result()
    for observation in result.observations:
        observation.value = 100.0
        observation.raw_value = "100"

    payload = export_pptx(result)
    deck = Presentation(io.BytesIO(payload))

    assert not any(shape.has_chart for slide in deck.slides for shape in slide.shapes)


def test_pptx_export_keeps_the_planned_chart_mix_editable() -> None:
    result = _result()
    base = result.charts[0]
    result.charts = [
        base.model_copy(update={"id": f"chart-{chart_type}", "chart_type": chart_type, "title": f"Revenue {chart_type}"})
        for chart_type in ("line", "bar", "area")
    ]

    deck = Presentation(io.BytesIO(export_pptx(result)))
    chart_types = [shape.chart.chart_type for slide in deck.slides for shape in slide.shapes if shape.has_chart]

    assert chart_types == [XL_CHART_TYPE.LINE_MARKERS, XL_CHART_TYPE.COLUMN_CLUSTERED, XL_CHART_TYPE.AREA]
