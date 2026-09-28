"""Conflict identity follows retained source meaning, never source location alone."""

import pytest

from adaptive_document_agent.extraction.comparison_context import restore_comparison_context
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models import Observation, SourceEvidence
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.validation import ExtractionValidator, SemanticValidator


def _table(table_id, page, rows, *, body=(), caption=()):
    return ExtractedTable(
        table_id=table_id, page=page, headers=["label", "FY2025"],
        column_periods=[None, "FY2025"], confidence=.9,
        rows=[TableRow(cells=row, page=page) for row in rows],
        raw_body_lines=list(body), raw_header_lines=list(caption),
        context_label="Information",
    )


def _conflicts(observations):
    return [issue for issue in ExtractionValidator().validate(observations).issues
            if issue.code == "conflicting_values"]


def test_group_headings_and_named_subtotals_disambiguate_repeated_rows():
    table = _table("grouped", 4, [
        ["Laboratory A Sample 1", "10"], ["Others", "20"], ["Subtotal of Laboratory A", "30"],
        ["Laboratory B Sample 1", "40"], ["Others", "50"], ["Subtotal of Laboratory B", "90"],
    ], body=["Laboratory A", "Sample 1 10", "Others 20", "Subtotal of Laboratory A 30",
             "Laboratory B", "Sample 1 40", "Others 50", "Subtotal of Laboratory B 90"])
    observations = ObservationExtractor()._table_observations(table)
    others = [o for o in observations if o.metric_original == "Others"]
    assert [o.parent_section for o in others] == ["Laboratory A", "Laboratory B"]
    assert [o.raw_value for o in others] == ["20", "50"]
    assert not _conflicts(observations)


def test_heading_word_inside_wrapped_row_is_not_enough_to_infer_parent():
    table = _table("ambiguous", 1, [
        ["Equipment Sample 1", "10"], ["Others", "20"], ["Others", "30"],
    ], body=["Equipment", "Sample 1 10", "Others 20", "Others 30"])
    observations = ObservationExtractor()._table_observations(table)
    assert all(o.parent_section is None for o in observations)
    assert len(_conflicts(observations)) == 1


@pytest.mark.parametrize("left,right", [
    ("trade receivables", "trade payables"),
    ("sample processing delays", "equipment maintenance delays"),
])
def test_caption_subjects_separate_shared_interval_buckets(left, right):
    tables = [_table(str(page), page, [["Within one year", str(page * 100)]], caption=[
        f"The following table sets forth an aging analysis of our {subject} based on invoice date",
        "as of the dates indicated.",
    ]) for page, subject in enumerate([left, right], start=1)]
    observations = [o for table in tables for o in ObservationExtractor()._table_observations(table)]
    assert [o.dimensions["table_context"] for o in observations] == [left, right]
    assert not _conflicts(observations)


def test_same_subject_different_pages_and_tables_still_conflicts():
    tables = [_table(str(page), page, [["Within one year", str(page * 100)]], caption=[
        f"The following table shows an aging analysis of {subject} based on invoice dates.",
    ]) for page, subject in [(1, "trade receivables"), (7, "Trade   Receivables")]]
    observations = [o for table in tables for o in ObservationExtractor()._table_observations(table)]
    assert len(_conflicts(observations)) == 1


def test_same_metric_with_different_surrounding_prose_still_conflicts():
    tables = [_table(str(page), page, [["Revenue", str(page * 100)]], caption=[
        f"The following table presents a summary of {subject} by year.",
    ]) for page, subject in enumerate(["performance", "operations"], start=1)]
    observations = [o for table in tables for o in ObservationExtractor()._table_observations(table)]
    assert len(_conflicts(observations)) == 1


def test_caption_keeps_explicit_breakdown_axis_for_other_categories():
    tables = [_table(str(page), page, [["Others", str(page * 100)]], caption=[
        f"The following table shows a breakdown of response counts by {axis} for the period indicated.",
    ]) for page, axis in enumerate(["department", "rating"], start=1)]
    observations = [o for table in tables for o in ObservationExtractor()._table_observations(table)]
    assert [o.dimensions["table_context"] for o in observations] == [
        "response counts by department", "response counts by rating"]
    assert not _conflicts(observations)


def test_conflicting_repeated_others_within_same_group_remain_errors():
    table = _table("grouped", 1, [
        ["Cohort A Sample 1", "10"], ["Others", "20"], ["Others", "30"],
        ["Subtotal of Cohort A", "60"],
    ], body=["Cohort A", "Sample 1 10", "Others 20", "Others 30", "Subtotal of Cohort A 60"])
    observations = ObservationExtractor()._table_observations(table)
    issue, = _conflicts(observations)
    assert len(issue.related_ids) == 2
    assert {source.text for source in issue.evidence} == {"20", "30"}


def test_same_group_in_different_tables_still_conflicts():
    tables = [_table(str(page), page, [
        ["Cohort A Sample 1", "10"], ["Others", str(page * 100)], ["Subtotal of Cohort A", "110"],
    ], body=["Cohort A", "Sample 1 10", f"Others {page * 100}", "Subtotal of Cohort A 110"])
        for page in [1, 2]]
    observations = [o for table in tables for o in ObservationExtractor()._table_observations(table)]
    for observation in observations:
        if observation.source_page == 2 and observation.parent_section:
            observation.parent_section = "COHORT A"
            observation.dimensions["section"] = "COHORT   A"
    issue, = _conflicts(observations)
    assert len(issue.related_ids) == 2


def test_percentage_others_keep_parent_and_never_merge_with_amounts():
    table = _table("shares", 1, [
        ["Cohort A Sample 1", "10", "25"], ["Others", "30", "75"],
        ["Subtotal of Cohort A", "40", "100"],
        ["Cohort B Sample 1", "50", "50"], ["Others", "50", "50"],
        ["Subtotal of Cohort B", "100", "100"],
    ], body=["Cohort A", "Cohort B"])
    table.headers = ["label", "Amount", "% of Total"]
    table.column_periods = [None, "FY2025", "FY2025"]
    table.column_types = ["label", "amount", "percentage"]
    observations = ObservationExtractor()._table_observations(table)
    others = [o for o in observations if o.metric_original.startswith("Others")]
    assert len(others) == 4
    assert [(o.value, o.parent_section) for o in others if o.unit == "percent"] == [
        (75, "Cohort A"), (50, "Cohort B")]
    assert not _conflicts(observations)


def test_old_snapshot_replay_preserves_all_facts_and_requires_matching_source():
    table = _table("buckets", 1, [["Within one year", "100"]], caption=[
        "The following table shows an aging analysis of trade receivables based on invoice date.",
    ])
    original = Observation(
        id="retained", metric_original="Within one year", raw_value="100", value=100,
        period="FY2025", confidence=.9, table_id=table.table_id, row_id=0, column_id=1,
        evidence=[SourceEvidence(page=1, text="100", table_id=table.table_id,
                                 row_label="Within one year", column_label="FY2025",
                                 extraction_method="digital_table", confidence=.9)],
    )
    before = original.model_dump()
    enriched, = restore_comparison_context([original], [table])
    assert enriched.dimensions == {"table_context": "trade receivables"}
    assert {k: v for k, v in enriched.model_dump().items() if k != "dimensions"} == {
        k: v for k, v in before.items() if k != "dimensions"}
    assert original.model_dump() == before
    bad = original.model_copy(update={"raw_value": "101"})
    assert restore_comparison_context([bad], [table])[0] is bad


@pytest.mark.parametrize("names,expected", [
    (["Adjusted net loss (non-IFRS measure)"] * 3, False),
    (["Adjusted net loss", " adjusted  NET loss "], False),
    (["Adjusted net loss", "Adjusted net losses"], False),
    (["Gross revenue", "Net revenue"], True),
    (["Adjusted net loss", "Net loss"], True),
    (["Revenue", "Total revenue"], True),
])
def test_over_normalization_compares_distinct_original_qualifier_sets(names, expected):
    observations = [Observation(id=str(index), metric_original=name, metric_canonical="measure",
                                raw_value="1", value=1, confidence=.9)
                    for index, name in enumerate(names)]
    issues = SemanticValidator().validate(observations).issues
    assert bool(issues) is expected
    assert all(issue.code == "possible_over_normalization" for issue in issues)
