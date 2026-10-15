"""Retained ambiguous tables remain visible in fresh and resumed reports."""

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.models import DocumentPage, DocumentProfile, ParsedDocument
from adaptive_document_agent.models.table import ExtractedTable


def test_source_header_diagnostic_survives_serialization_and_reporting_retry():
    source = ExtractedTable(table_id='source-1', page=1, confidence=.9,
        raw_cells=[['Category A', '25', '62.5'], ['Category B', '15', '37.5']])
    table = TableExtractor()._analytical_copy(source)
    document = ParsedDocument.model_validate_json(ParsedDocument(
        document_id='synthetic', sha256='synthetic', safe_filename='synthetic.pdf', page_count=1,
        pages=[DocumentPage(page_number=1, tables=[table], raw_tables=[source])],
    ).model_dump_json())
    original = document.model_dump()
    runner = DocumentOrchestrator()
    index = DocumentIndex([])
    fresh = runner._generate_report(document, DocumentProfile(), index, [], [], [], lambda _: None, None)
    resumed = runner._generate_report(document, DocumentProfile(), index, [], [],
                                     fresh.validation_warnings, lambda _: None, None)
    for output in (fresh, resumed):
        warnings = [issue for issue in output.validation_warnings
                    if issue.code == 'ambiguous_source_table_header']
        assert len(warnings) == 1
        assert warnings[0].related_ids == ['source-1']
        assert warnings[0].evidence[0].page == 1
        assert warnings[0].message in output.report_markdown
        assert not output.observations and not output.charts
    assert document.model_dump() == original
