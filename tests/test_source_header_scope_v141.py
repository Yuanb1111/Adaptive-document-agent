"""Literal source columns need aligned evidence, never caption-year guesses."""

from copy import deepcopy

import pytest

from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.source_header_scope import source_header_issues
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.models import DocumentPage, ParsedDocument
from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.validation import ExtractionValidator


def literal(headers, rows, *, page=1, lines=(), spans=()):
    return ExtractedTable(table_id=f"source_{page}", page=page, confidence=.9,
        raw_header_cells=headers, raw_header_lines=list(lines), raw_header_spans=list(spans),
        raw_cells=rows, source_layout_status="checked")


def analytical(table):
    before=deepcopy(table.model_dump())
    result=TableExtractor()._analytical_copy(table)
    assert table.model_dump()==before
    assert result.raw_cells==table.raw_cells
    assert result.raw_header_cells==table.raw_header_cells
    assert result.raw_header_spans==table.raw_header_spans
    return result


def test_nearest_complete_year_row_supersedes_caption_ranges_and_chart_annotations():
    source=literal([
        ["", "Market totals by category, 2020-2026E", "", "", ""],
        ["", "CAGR 2020-2023 CAGR 2023-2026E", "", "", ""],
        ["", "Group A", "12.5%", "", "16.5%"],
        ["", "2020", "2021", "2025E", "2026E"],
    ], [["Category A", "250", "330", "510", "720"],
        ["Category B", "110", "130", "190", "230"]], spans=[(0,1,4),(1,1,4)])
    table=analytical(source)
    assert table.column_periods==[None,"2020","2021","2025E","2026E"]
    assert table.column_types==["label","amount","amount","amount","amount"]
    observations=ObservationExtractor()._table_observations(table)
    assert len(observations)==8
    assert all(o.unit!="percent" for o in observations)
    assert not ExtractionValidator().validate(observations).issues
    assert table.raw_cells_include_headers is False


def test_deeper_financial_roles_keep_grouped_annual_and_interim_columns():
    source=literal([
        ["", "Historical results 2020-2026", "", "", ""],
        ["", "FY2024", "", "6M2025", ""],
        ["", "RMB'000", "%", "RMB'000", "%"],
        ["", "", "", "(Unaudited)", "(Unaudited)"],
    ], [["Revenue","240","100","130","100"],
        ["Gross profit","110","45.8","61","46.9"]],
        spans=[(0,1,4),(1,1,2),(1,3,4)])
    table=analytical(source)
    assert table.column_periods==[None,"FY2024","FY2024","6M2025","6M2025"]
    assert table.column_types==["label","amount","percentage","amount","percentage"]
    assert table.column_currencies==[None,"CNY",None,"CNY",None]
    assert table.column_scales==[None,1000,1,1000,1]
    observations=ObservationExtractor()._table_observations(table)
    assert len(observations)==8
    assert {o.period for o in observations}=={"FY2024","6M2025"}
    assert {o.raw_value for o in observations}=={"240","100","130","110","45.8","61","46.9"}


def test_explicit_aligned_cagr_intervals_are_preserved_in_full():
    source=literal([["", "CAGR 2020–2023", "CAGR 2023–2026E"]],
                   [["Category A","11.2%","18.4%"],["Category B","7.5%","9.8%"]])
    table=analytical(source)
    assert table.column_periods==[None,"CAGR 2020–2023","CAGR 2023–2026E"]
    assert table.column_types==["label","percentage","percentage"]
    observations=ObservationExtractor()._table_observations(table)
    assert len(observations)==4
    assert not [w for w in ExtractionValidator().validate(observations).issues if w.code=="conflicting_values"]


@pytest.mark.parametrize("headers,rows",[
    ([["", "CAGR 2020-2023 CAGR 2023-2026E", ""]],
     [["Category A","11.2%","18.4%"]]),
    ([],[["Sub-total","25","62.5"],["Others","15","37.5"]]),
    ([["", "Market totals by category, 2020-2026E", ""]],
     [["Category A","250","510"]]),
])
def test_unproved_multi_column_headers_quarantine_analytics_but_keep_source(headers,rows):
    source=literal(headers,rows)
    table=analytical(source)
    assert all(row.alignment_status=="ambiguous" for row in table.rows)
    assert ObservationExtractor()._table_observations(table)==[]
    document=ParsedDocument(document_id="synthetic",sha256="synthetic",safe_filename="synthetic.pdf",
                            page_count=1,pages=[DocumentPage(page_number=1,tables=[table],raw_tables=[source])])
    issue,=source_header_issues(document)
    assert issue.code=="ambiguous_source_table_header"
    assert issue.related_ids==[table.table_id]
    assert issue.evidence[0].page==1
    assert "raw source cells are retained" in issue.message


def test_expanding_one_range_caption_is_not_independent_column_period_evidence():
    source=literal([["","2020-2026E",""]],[["Category A","250","510"]],spans=[(0,1,2)])
    table=analytical(source)
    assert all(row.alignment_status=="ambiguous" for row in table.rows)
    assert table.column_periods==[None,None,None]
    assert ObservationExtractor()._table_observations(table)==[]


def test_explicit_single_year_span_remains_valid_for_amount_and_percentage_columns():
    source=literal([["","FY2025",""],["","RMB'000","%"]],
                   [["Revenue","280","100"]],spans=[(0,1,2)])
    table=analytical(source)
    assert table.column_periods==[None,"FY2025","FY2025"]
    assert table.column_types==["label","amount","percentage"]
    assert len(ObservationExtractor()._table_observations(table))==2


@pytest.mark.parametrize('count_label,ratio_label',[
    ('Output volume','Utilization (%)'),('数量','利用率(%)'),
])
def test_aligned_measure_tiers_above_leaf_years_keep_count_and_percentage_roles(count_label,ratio_label):
    source=literal([
        ["",count_label,"",ratio_label,""],
        ["","2024","2025","2024","2025"],
    ],[["Line A","120","140","60","70"]],spans=[(0,1,2),(0,3,4)])
    table=analytical(source)
    assert table.column_periods==[None,"2024","2025","2024","2025"]
    assert table.column_types==["label","count","count","percentage","percentage"]
    observations=ObservationExtractor()._table_observations(table)
    assert len(observations)==4
    assert {o.unit for o in observations if o.column_id in {3,4}}=={"percent"}


def test_explicit_interval_span_with_separate_measure_roles_is_a_proven_group():
    source=literal([["","CAGR 2020–2023",None],["","Units","%"]],
        [["Category A","120","18.4"]],spans=[(0,1,2)])
    table=analytical(source)
    assert table.column_periods==[None,"CAGR 2020–2023","CAGR 2020–2023"]
    assert table.column_types==["label","count","percentage"]


def test_period_row_cannot_hide_a_numeric_column_with_no_source_header():
    source=literal([["",None,"FY2023","FY2024"]],[["Category A","120","130","140"]])
    table=analytical(source)
    assert all(row.alignment_status=="ambiguous" for row in table.rows)
    assert ObservationExtractor()._table_observations(table)==[]


@pytest.mark.parametrize('years',[["","FY2024",None,"FY2025"],["","FY2024",None,None]])
def test_neighboring_blank_cells_cannot_borrow_a_period_without_a_literal_span(years):
    source=literal([years,["","RMB'000","%","RMB'000"]],
                   [["Revenue","120","100","140"]])
    table=analytical(source)
    assert all(row.alignment_status=="ambiguous" for row in table.rows)
    assert table.column_periods==[None,None,None,None]
    assert ObservationExtractor()._table_observations(table)==[]


def test_numeric_body_years_never_supply_missing_column_headers():
    source=literal([],[["Category A","2021","2022"],["Category B","2023","2024"]])
    table=analytical(source)
    assert table.column_periods==[None,None,None]
    assert ObservationExtractor()._table_observations(table)==[]


def test_unheaded_qualitative_grid_does_not_create_a_numeric_alignment_warning():
    source=literal([],[["Team A","design","active"],["Team B","support","planned"]])
    table=analytical(source)
    assert not table.warnings
    assert ObservationExtractor()._table_observations(table)==[]


@pytest.mark.parametrize('left_caption,right_caption',[
    ("Market size for the global testing services industry",
     "Market size for the regional testing services industry"),
    ("Market size for product family 1","Market size for product family 2"),
    ("不同业务类别在全球市场的营业收入比较","不同业务类别在区域市场的营业收入比较"),
])
def test_explicit_distinct_captions_prevent_false_continuation_even_with_same_years(left_caption,right_caption):
    first=analytical(literal([["","FY2024","FY2025"]],[["Category A","25","28"]],
        lines=["INDUSTRY OVERVIEW",left_caption]))
    second=analytical(literal([["","FY2024","FY2025"]],[["Category A","12","14"]],page=2,
        lines=["INDUSTRY OVERVIEW",right_caption]))
    assert len(TableReconstructor().combine_continuations([first,second]))==2


def test_same_caption_continuation_still_joins_and_keeps_row_pages():
    first=analytical(literal([["","FY2024","FY2025"]],[["Category A","25","28"]],
        lines=["Market size for the global testing services industry"]))
    second=analytical(literal([["","FY2024","FY2025"]],[["Category B","12","14"]],page=2,
        lines=["Market size for the global testing services industry (continued)"]))
    combined=TableReconstructor().combine_continuations([first,second])
    assert len(combined)==1
    assert [row.page for row in combined[0].rows]==[1,2]


def test_explicit_short_table_titles_are_never_ignored_for_continuation_identity():
    first=analytical(literal([["","FY2024","FY2025"]],[["Category A","25","28"]]))
    second=first.model_copy(deep=True,update={"page":2,"table_id":"second"})
    first.table_title="Revenue"
    second.table_title="Expenses"
    assert len(TableReconstructor().combine_continuations([first,second]))==2


def test_quarantined_header_does_not_borrow_a_valid_continuation_scope():
    first=analytical(literal([],[["Sub-total","25","62.5"]]))
    second=first.model_copy(deep=True,update={"page":2,"table_id":"second"})
    assert len(TableReconstructor().combine_continuations([first,second]))==2
