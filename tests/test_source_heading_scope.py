"""Literal table hierarchy qualifies metrics across financial and other domains."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.document_model.series import metric_identity_key
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.comparison_context import restore_comparison_context
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.presentation_labels import qualified_metric_name
from adaptive_document_agent.validation.insight_context import qualified_metric_label


def source_table(parent="Completed visits", child="Follow-up"):
    return ExtractedTable(
        table_id="scope", page=3, headers=["Measure", "2024", "2025"],
        column_periods=[None, "FY2024", "FY2025"], confidence=.9,
        raw_header_lines=["2024 2025", parent],
        rows=[TableRow(cells=[child, "11", "14"], page=3),
              TableRow(cells=["Other samples", "8", "9"], page=3),
              TableRow(cells=[f"Total {parent}", "19", "23"], page=3),
              TableRow(cells=["Independent measure", "20", "25"], page=3)],
    )


@pytest.mark.parametrize("parent,child", [
    ("Current assets", "Trade and bills receivables"),
    ("Completed visits", "Follow-up"),
    ("Respondents choosing remote work", "Engineering"),
    ("Discarded batches", "Plant North"),
])
def test_first_header_group_is_qualified_in_analysis_and_presentation(parent, child):
    table = source_table(parent, child)
    retained = deepcopy(table)
    observations = ObservationExtractor()._table_observations(table)
    selected = [item for item in observations if item.row_id == 0]
    assert len(selected) == 2
    for item in selected:
        assert item.metric_original == child
        assert item.parent_section == parent
        assert item.dimensions["section"] == parent
        assert item.evidence[0].row_label == child
        assert item.evidence[0].page == 3
        assert display_metric_name(item) == f"{parent}: {child}"
        assert qualified_metric_name(item) == f"{parent}: {child}"
        assert qualified_metric_label(item) == f"{parent}: {child}"
        unscoped = item.model_copy(update={"parent_section": None, "dimensions": {}})
        assert metric_identity_key(item) != metric_identity_key(unscoped)
    assert [item.raw_value for item in selected] == ["11", "14"]
    assert all(item.parent_section is None for item in observations if item.row_id >= 2)
    assert table == retained


def test_borderless_first_group_heading_survives_header_body_split():
    page = SimpleNamespace(text="""Inspection results
Year ended December 31,
2024 2025
Rejected samples
Plant North .... 11 14
Plant South .... 8 9
Total rejected samples .... 19 23
Independent measure .... 20 25
""")
    table, = BorderlessTableExtractor().extract(page, 3)
    assert table.raw_header_lines[-1] == "Rejected samples"
    observations = ObservationExtractor()._table_observations(table)
    north = [item for item in observations if item.metric_original == "Plant North"]
    assert [item.value for item in north] == [11, 14]
    assert all(item.parent_section == "Rejected samples" for item in north)
    assert all("Rejected samples" in qualified_metric_name(item) for item in north)


@pytest.mark.parametrize("fault", [
    "no_heading", "heading_in_caption_only", "no_named_total", "different_total",
    "intervening_heading", "ambiguous_row", "different_page", "unit_after_heading",
])
def test_header_scope_recovery_requires_both_literal_boundaries(fault):
    table = source_table()
    if fault == "no_heading":
        table.raw_header_lines = []
    elif fault == "heading_in_caption_only":
        table.raw_header_lines = ["The table shows Completed visits."]
    elif fault == "no_named_total":
        table.rows[2].cells[0] = "Total"
    elif fault == "different_total":
        table.rows[2].cells[0] = "Total scheduled visits"
    elif fault == "intervening_heading":
        table.rows[1] = TableRow(cells=["Other source scope", None, None], page=3)
    elif fault == "ambiguous_row":
        table.rows[1].alignment_status = "ambiguous"
    elif fault == "different_page":
        table.rows[1].page = 4
    elif fault == "unit_after_heading":
        table.raw_header_lines.append("(counts)")
    observations = ObservationExtractor()._table_observations(table)
    assert all(item.parent_section is None for item in observations if item.row_id == 0)


@pytest.mark.parametrize("first,second", [("Current", "Non-current"), ("Other", "Deferred")])
def test_short_literal_headings_are_not_dropped_and_bare_totals_close_scope(first, second):
    table = source_table()
    table.raw_header_lines = []
    table.rows = [TableRow(cells=cells, page=3) for cells in [
        [first + ":", None, None], ["Samples", "11", "14"], ["Total", "11", "14"],
        ["Independent measure", "20", "25"],
        [second, None, None], ["Samples", "8", "9"], ["Total", "8", "9"],
        ["Independent measure", "30", "35"],
    ]]
    observations = ObservationExtractor()._table_observations(table)
    samples = [item for item in observations if item.metric_original == "Samples"]
    assert [item.parent_section for item in samples] == [first, first, second, second]
    assert metric_identity_key(samples[0]) != metric_identity_key(samples[2])
    assert all(item.parent_section is None for item in observations
               if item.metric_original == "Independent measure")


def test_exact_cell_replay_adds_scope_without_rewriting_source_facts():
    table = source_table()
    original = ObservationExtractor()._table_observations(table)[0]
    original.parent_section = None
    original.dimensions.pop("section")
    before = original.model_dump()
    restored, = restore_comparison_context([original], [table])
    assert restored.parent_section == "Completed visits"
    assert restored.dimensions["section"] == "Completed visits"
    changed = {key for key, value in restored.model_dump().items() if value != before[key]}
    assert changed == {"parent_section", "dimensions"}
    assert original.model_dump() == before
    for field, value in [("raw_value", "12"), ("column_id", 2), ("table_id", "unrelated")]:
        mismatched = original.model_copy(update={field: value})
        assert restore_comparison_context([mismatched], [table])[0] is mismatched
