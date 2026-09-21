"""Regression contracts for staggered headers and sparse numeric rows.

Fixtures are issuer-independent and exercise geometry, not numeric thresholds.
"""

import pytest

from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.models import DocumentPage, DocumentProfile, ParsedDocument, PipelineResult
from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data


class TextPage:
    def __init__(self, text):
        self.text = text


class PositionedPage:
    def __init__(self, currency="USD"):
        self.words = []
        self.lines = []
        self.row("Gross Profit and Gross Profit Margin", 10, 30)
        self.row("Year ended December 31,", 30, 340)
        for year, x in zip(("2021", "2022", "2023"), (290, 410, 530)):
            self.word(year, 50, x)
        for x in (340, 460, 580):
            self.word("Gross", 70, x)
        for x in (280, 400, 520):
            self.word("Gross", 82, x)
            self.word("profit", 94, x)
        for x in (340, 460, 580):
            self.word("profit", 82, x)
            self.word("margin", 94, x)
        for x in (280, 400, 520):
            self.word(f"({currency})", 110, x)
        for x in (340, 460, 580):
            self.word("(%)", 110, x)
        self.row(f"({currency} in thousands, except for percentages)", 125, 270)
        self.data("Products", 145, ["30,403", "16.7", "71,190", "26.5", "101,628", "24.8"])
        self.data("– Services", 165, ["(937)", "(33.9)", "2,167", "30.6", "5,025", "10.7"])
        self.data("Less: write-down of inventories", 185, ["(14,484)", None, "(8,212)", None, "(6,272)", None])
        self.data("Percentages only", 205, [None, "12.5", None, "13.5", None, "14.5"])

    def word(self, text, y, center):
        width = len(text)*4
        self.words.append({"text": text, "x0": center-width/2, "x1": center+width/2, "top": y, "bottom": y+9})

    def row(self, text, y, x):
        for word in text.split():
            self.word(word, y, x+len(word)*2)
            x += len(word)*4+3

    def data(self, label, y, values):
        self.row(label, y, 30)
        for right, value in zip((295, 355, 415, 475, 535, 595), values):
            if value is not None:
                self.word(value, y, right-len(value)*2)

    def extract_words(self, **kwargs):
        return self.words

    def extract_text(self, **kwargs):
        # The geometric path does not infer missing cells from this collapsed
        # string. Row spacing and value positions are provided by source words.
        return "unused collapsed text"


def result_for(table):
    document = ParsedDocument(document_id="source", sha256="source", safe_filename="source.pdf", page_count=1,
                              pages=[DocumentPage(page_number=1, text="", tables=[table])])
    return PipelineResult(document=document, profile=DocumentProfile(), observations=ObservationExtractor().extract(document))


@pytest.mark.parametrize("currency", ["USD", "RMB", "HKD", "EUR"])
def test_staggered_headers_preserve_amounts_percentages_and_source(currency):
    table = BorderlessTableExtractor().extract(PositionedPage(currency), 1)[0]
    assert table.headers[1:] == ["Gross profit", "Gross profit margin"]*3
    assert table.column_types[1:] == ["amount", "percentage"]*3
    assert table.raw_header_lines
    result = result_for(table)
    assert not validate_presentation_data(result)
    amount = next(o for o in result.observations if o.raw_value == "30,403")
    assert amount.value == 30_403_000 and amount.unit == "currency"
    assert amount.evidence[0].page == 1 and amount.evidence[0].column_label == "Gross profit"
    loss = next(o for o in result.observations if o.raw_value == "(937)")
    margin = next(o for o in result.observations if o.raw_value == "(33.9)")
    assert loss.value == -937_000 and loss.unit == "currency"
    assert margin.value == -33.9 and margin.unit == "percent"
    assert margin.dimensions["category"] == "Services"


def test_sparse_rows_align_from_positions_not_amount_or_percentage_magnitude():
    table = BorderlessTableExtractor().extract(PositionedPage(), 1)[0]
    deduction = next(r for r in table.rows if r.cells[0].startswith("Less:"))
    assert deduction.cells[1:] == ["(14,484)", None, "(8,212)", None, "(6,272)", None]
    percentages = next(r for r in table.rows if r.cells[0] == "Percentages only")
    assert percentages.cells[1:] == [None, "12.5", None, "13.5", None, "14.5"]
    obs = ObservationExtractor()._table_observations(table)
    deductions = [o for o in obs if o.row_operator == "subtractive"]
    assert [o.period for o in deductions] == ["FY2021", "FY2022", "FY2023"]
    assert [o.value for o in deductions] == [-14_484_000, -8_212_000, -6_272_000]
    assert all(o.unit == "currency" for o in deductions)
    assert all(o.unit == "percent" for o in obs if o.dimensions.get("category") == "Percentages only")


@pytest.mark.parametrize("bullet", ["–", "—", "-", "•", "�C"])
def test_row_bullets_do_not_become_missing_values_or_section_headings(bullet):
    page = TextPage(f"""Breakdown
Year ended December 31,
2021 2022 2023
Gross Gross Gross
Gross profit Gross profit Gross profit
profit margin profit margin profit margin
(USD) (%) (USD) (%) (USD) (%)
(USD in thousands, except for percentages)
Products 1,100 11.0 2,200 22.0 3,300 33.0
{bullet} Services (100) (1.5) 200 2.5 300 3.5
Other products 800 8.5 900 9.5 950 9.9
""")
    table = BorderlessTableExtractor().extract(page, 1)[0]
    assert [r.cells[0] for r in table.rows] == ["Products", "Services", "Other products"]
    observations = ObservationExtractor()._table_observations(table)
    assert len(observations) == 18
    assert all("1.5" not in o.metric_original and not o.metric_original.startswith("% of profit") for o in observations)
    assert all(o.unit == "currency" for o in observations if o.raw_value in {"1,100", "(100)", "900"})
    assert all(o.unit == "percent" for o in observations if o.raw_value in {"11.0", "(1.5)", "9.5"})


def test_except_percentages_note_is_not_evidence_for_other_columns():
    page = TextPage("""Year ended December 31,
2021 2022 2023
Profit Profit Profit
(USD in thousands, except for percentages)
Products 10,000 20,000 30,000
Services 1,000 2,000 3,000
""")
    table = BorderlessTableExtractor().extract(page, 1)[0]
    assert table.headers[1:] == ["Profit"]*3
    assert table.column_types[1:] == ["amount"]*3
    assert all(o.unit == "currency" for o in ObservationExtractor()._table_observations(table))


def test_collapsed_sparse_row_is_retained_and_reported_not_guessed():
    page = TextPage("""Year ended December 31,
2021 2022 2023
Amount % Amount % Amount %
(USD in thousands)
Sales 10,000 10 20,000 20 30,000 30
Costs 5,000 5 6,000 6 7,000 7
Less: impairment (100) (200) (300)
""")
    table = BorderlessTableExtractor().extract(page, 1)[0]
    row = table.rows[-1]
    assert row.alignment_status == "ambiguous" and row.cells[1:4] == ["(100)", "(200)", "(300)"]
    result = result_for(table)
    assert not any(o.raw_value in {"(100)", "(200)", "(300)"} for o in result.observations)
    assert any(i.code == "ambiguous_table_alignment" and i.severity == "CRITICAL" for i in validate_presentation_data(result))


def test_percentage_problems_still_block_after_fix():
    table = BorderlessTableExtractor().extract(PositionedPage(), 1)[0]
    result = result_for(table)
    ratio = next(o for o in result.observations if o.unit == "percent")
    ratio.value = 30_403
    assert any(i.code == "implausible_percentage" for i in validate_presentation_data(result))


def test_reconstruction_keeps_evidenced_sparse_cells_and_header_fragments():
    table = BorderlessTableExtractor().extract(PositionedPage(), 1)[0]
    rebuilt = TableReconstructor().reconstruct(table)
    assert rebuilt.raw_cells == table.raw_cells
    assert rebuilt.raw_header_lines == table.raw_header_lines
    assert [r.cells for r in rebuilt.rows] == [r.cells for r in table.rows]


def test_explicit_unit_only_header_does_not_depend_on_column_adjacency():
    page = TextPage("""Year ended December 31,
2021 2022 2023
(%) (USD) (%) (USD) (%) (USD)
(USD in thousands, except for percentages)
Goods 10 1,000 20 2,000 30 3,000
Services 15 1,500 25 2,500 35 3,500
""")
    table = BorderlessTableExtractor().extract(page, 1)[0]
    assert table.column_types[1:] == ["percentage", "amount"]*3


def test_multiword_percentage_heading_stays_in_its_own_column():
    page = PositionedPage()
    page.words = [w for w in page.words if w["top"] < 60 or w["top"] >= 125]
    for x in (265, 385, 505):
        page.row("Amount", 80, x)
        # The '%' alone is nearer the preceding amount's numeric center.
        # The complete phrase is over the percentage column.
        page.row("% of Total", 80, x+41)
    table = BorderlessTableExtractor().extract(page, 1)[0]
    assert table.headers[1:] == ["Amount", "% of Total"]*3
    assert table.column_types[1:] == ["amount", "percentage"]*3
    assert not validate_presentation_data(result_for(table))


def test_wrapped_sparse_row_keeps_ambiguity_after_label_reconstruction():
    page = TextPage("""Year ended December 31,
2021 2022 2023
Amount % Amount % Amount %
(USD in thousands)
Sales 10,000 10 20,000 20 30,000 30
Costs 5,000 5 6,000 6 7,000 7
Less: impairment of
inventories (100) (200) (300)
""")
    table = BorderlessTableExtractor().extract(page, 1)[0]
    row = table.rows[-1]
    assert row.cells[0] == "Less: impairment of inventories"
    assert row.alignment_status == "ambiguous"
    assert any(i.code == "ambiguous_table_alignment" for i in validate_presentation_data(result_for(table)))


def test_minus_signs_and_missing_cells_are_not_label_bullets():
    row = BorderlessTableExtractor._parse_row(0, "– Services -100 – (200) - 300 30")
    assert row.label == "Services"
    assert row.values == ["-100", "–", "(200)", "-", "300", "30"]
