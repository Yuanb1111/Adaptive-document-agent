"""Numeric prose must not become a sparse row in an adjacent table."""

import pytest

from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models import DocumentPage, DocumentProfile, ParsedDocument, PipelineResult
from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data


@pytest.mark.parametrize("text", [
    "December 31, 2025 had been settled.",
    "March 31, 2024 remained outstanding.",
    "September 30, 2022",
    "Orders 100 200 were completed.",
    "Orders .... 100 and 200 were completed.",
    "Orders .... 100 shipped 200",
    "Balance 100 200 尚未支付。",
])
def test_dates_and_trailing_or_interleaved_prose_are_not_table_rows(text):
    assert BorderlessTableExtractor._parse_row(0, text) is None


@pytest.mark.parametrize("text,values", [
    ("December 31 40 50", ["31", "40", "50"]),
    ("Revenue .... 31,000 42,000 53,000", ["31,000", "42,000", "53,000"]),
    ("Loss .... (1,500) -200 300", ["(1,500)", "-200", "300"]),
    ("Margin 12.5% (3.1)% 18.2%", ["12.5%", "(3.1)%", "18.2%"]),
    ("Amounts 10 20 30*", ["10", "20", "30"]),
    ("Amounts 10 20 30 (a)", ["10", "20", "30"]),
    ("Balances 10 – -", ["10", "–", "-"]),
])
def test_discrete_numeric_cells_and_valid_month_labels_are_preserved(text, values):
    row = BorderlessTableExtractor._parse_row(0, text)
    assert row is not None and row.values == values


class ProseAfterTablePage:
    text = """AGING ANALYSIS
As of December 31,
2021 2022 2023
(USD in thousands)
Within one year 10,000 20,000 30,000
One to two years 2,000 3,000 4,000
Total 12,000 23,000 34,000
As of April 30, 2024, approximately half of the balance as of
December 31, 2023 had been settled.
"""


def test_wrapped_date_narrative_does_not_trigger_false_alignment_blocker():
    source = ProseAfterTablePage()
    tables = BorderlessTableExtractor().extract(source, 1)
    document = ParsedDocument(document_id="synthetic", sha256="synthetic", safe_filename="source.pdf", page_count=1,
        pages=[DocumentPage(page_number=1, text=source.text, tables=tables)])
    observations = ObservationExtractor().extract(document)
    result = PipelineResult(document=document, profile=DocumentProfile(), observations=observations)
    assert len(tables) == 1 and len(tables[0].rows) == 3
    assert all(row.alignment_status == "resolved" for row in tables[0].rows)
    assert not validate_presentation_data(result)
    assert [o.value for o in observations if o.metric_original == "Within one year"] == [10_000_000, 20_000_000, 30_000_000]
    assert not any(o.metric_original == "December" for o in observations)
    assert "December 31, 2023 had been settled." in document.pages[0].text


def test_real_sparse_data_still_blocks_without_column_evidence():
    source = ProseAfterTablePage()
    # Use an unambiguous table context, not the narrative after its boundary.
    source.text = source.text[:source.text.index("As of April 30")] + "Impairment (100) (200)\n"
    tables = BorderlessTableExtractor().extract(source, 1)
    document = ParsedDocument(document_id="synthetic", sha256="synthetic", safe_filename="source.pdf", page_count=1,
        pages=[DocumentPage(page_number=1, text=source.text, tables=tables)])
    result = PipelineResult(document=document, profile=DocumentProfile(), observations=ObservationExtractor().extract(document))
    assert tables[0].rows[-1].cells[:3] == ["Impairment", "(100)", "(200)"]
    assert tables[0].rows[-1].alignment_status == "ambiguous"
    assert any(i.code == "ambiguous_table_alignment" and i.severity == "CRITICAL" for i in validate_presentation_data(result))
    assert not any(o.metric_original == "Impairment" for o in result.observations)
