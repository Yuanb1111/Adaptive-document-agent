import pymupdf

from adaptive_document_agent.models import DocumentProfile, ParsedDocument, PipelineResult, ReportPlan
from adaptive_document_agent.services.export import export_csv, export_json, export_markdown, export_pdf
from tests.test_pipeline import synthetic_time_series_pdf
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator


def test_exports_include_raw_values_and_profile() -> None:
    result = DocumentOrchestrator().analyse_pdf(synthetic_time_series_pdf())
    assert b"Raw Value" not in export_csv(result)
    assert b"raw_value" in export_csv(result)
    assert b"unit_scale" in export_csv(result)
    assert b"profile" in export_json(result)
    assert export_markdown(result).startswith(b"# ")
    pdf = export_pdf(result)
    assert pdf.startswith(b"%PDF")
    assert pymupdf.open(stream=pdf, filetype="pdf").page_count >= 1


def test_formal_pdf_omits_technical_diagnostics() -> None:
    result = PipelineResult(
        document=ParsedDocument(document_id="doc", sha256="abc", safe_filename="source.pdf", page_count=1),
        profile=DocumentProfile(),
        report_plan=ReportPlan(title="Report"),
        report_markdown=(
            "# Report\n\n## Data Quality and Limitations\n\n"
            "- Source table extraction should be reviewed.\n"
            "- [ERROR] Conflicting values for Others.\n"
            "- [WARNING] No retained observation matched a priority topic.\n"
            "- [INFO] Additional issues are retained in technical data.\n"
        ),
    )

    pdf = export_pdf(result)
    text = "\n".join(page.get_text() for page in pymupdf.open(stream=pdf, filetype="pdf"))

    assert "Source table extraction should be reviewed" in text
    assert "[ERROR]" not in text
    assert "[WARNING]" not in text
    assert "[INFO]" not in text
