from adaptive_document_agent.services.export import export_csv, export_json, export_markdown
from tests.test_pipeline import synthetic_time_series_pdf
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator


def test_exports_include_raw_values_and_profile() -> None:
    result = DocumentOrchestrator().analyse_pdf(synthetic_time_series_pdf())
    assert b"Raw Value" not in export_csv(result)
    assert b"raw_value" in export_csv(result)
    assert b"unit_scale" in export_csv(result)
    assert b"profile" in export_json(result)
    assert export_markdown(result).startswith(b"# ")
