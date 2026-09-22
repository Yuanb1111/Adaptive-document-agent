"""Label annotations must not become data columns; preserve real negatives."""

import pytest

from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.numeric_parser import parse_number
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data
from tests.test_borderless_alignment_regressions import PositionedPage, TextPage, result_for


@pytest.mark.parametrize("label,expected", [
    ("Completion rate(7)(12)", "Completion rate"),
    ("Adjusted score (reported)(4)", "Adjusted score (reported)"),
    ("Response rate(2)", "Response rate"),
])
def test_attached_label_footnotes_are_not_numeric_cells(label, expected):
    row = BorderlessTableExtractor._parse_row(0, f"{label} (2) (4) (8)")
    assert row.label == expected
    assert row.values == ["(2)", "(4)", "(8)"]


def test_adjacent_accounting_values_are_not_label_annotations():
    # There is no evidenced cell separator; never fix this by deleting '(4)'.
    assert BorderlessTableExtractor._parse_row(0, "Change (2)(4) (8)") is None


@pytest.mark.parametrize("raw", ["(12.5)%", "(12.5) %", "(12.5％)", "(12.5)％", "(12.5%)"])
def test_accounting_percent_preserves_source_and_negative_sign(raw):
    number = parse_number(raw)
    assert number.raw_value == raw and number.value == -12.5 and number.unit == "percent"


class FootnotedPage(PositionedPage):
    def __init__(self, prefix="Completion rate for", continuation="ABC systems", marker="(7)(12)"):
        self.words = []
        self.row("Year ended December 31,", 10, 270)
        for year, center in zip(("2020", "2021", "2022"), (295, 415, 535)):
            self.word(year, 30, center)
        self.values("Overall completion(1)", 55, ("10%", "20%", "30%"))
        self.values("Other completion(3)", 75, ("15%", "25%", "35%"))
        self.row(prefix, 95, 30)
        self.values(continuation + marker, 106, ("12%", "22%", "32%"), left=40)
        self.row("Adjusted change (reported", 126, 30)
        self.values("measure)(4)", 137, ("(8.5)%", "(4.5)%", "(2.5)%"), left=40)

    def values(self, label, y, values, left=30):
        self.row(label, y, left)
        for right, value in zip((305, 425, 545), values):
            self.word(value, y, right-len(value)*2)


@pytest.mark.parametrize("prefix,continuation", [("Completion rate for", "ABC systems"),
    ("Energy output from", "Solar units"), ("Survey participation in", "Regional teams")])
def test_wrapped_uppercase_labels_use_geometry_not_domain_keywords(prefix, continuation):
    table = BorderlessTableExtractor().extract(FootnotedPage(prefix, continuation), 1)[0]
    assert table.column_periods == [None, "FY2020", "FY2021", "FY2022"]
    assert len(table.rows) == 4
    assert table.rows[2].cells[0] == prefix + " " + continuation
    assert table.rows[3].cells == ["Adjusted change (reported measure)", "(8.5)%", "(4.5)%", "(2.5)%"]
    assert all(r.alignment_status == "resolved" for r in table.rows)
    assert any("(7)(12)" in line for line in table.raw_body_lines)
    rebuilt = TableReconstructor().reconstruct(table)
    assert rebuilt.raw_body_lines == table.raw_body_lines
    result = result_for(rebuilt)
    assert len(result.observations) == 12
    assert [o.value for o in result.observations[-3:]] == [-8.5, -4.5, -2.5]
    assert not validate_presentation_data(result)


def test_section_heading_and_bullet_child_are_not_joined():
    page = FootnotedPage(prefix="Service categories:", continuation="– Support teams")
    table = BorderlessTableExtractor().extract(page, 1)[0]
    labels = [r.cells[0] for r in table.rows]
    assert "Service categories" in labels and "Support teams" in labels


def test_footnote_fix_does_not_resolve_real_missing_columns_without_geometry():
    page = TextPage("Year ended December 31,\n2020 2021 2022\n"
                    "First measure(2)(3) 10 20 30\nSecond measure(4) 40 50 60\nSparse measure(5)(6) (2) (4)\n")
    table = BorderlessTableExtractor().extract(page, 1)[0]
    assert table.rows[-1].cells[1:] == ["(2)", "(4)", None]
    assert table.rows[-1].alignment_status == "ambiguous"
    assert any(i.code == "ambiguous_table_alignment" for i in validate_presentation_data(result_for(table)))
