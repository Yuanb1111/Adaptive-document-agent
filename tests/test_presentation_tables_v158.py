"""Coherent source tables retain complete rows and distinguish literal dashes."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from adaptive_document_agent.models import PresentationSlide, PresentationTopicSelection
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.presentation_source_cells import compact_source_table, literal_empty_source_cell
from adaptive_document_agent.services.presentation_section_titles import section_heading
from tests.test_topic_coverage_review import _observation, _topic


def source_fixture():
    items = [_observation(metric, period, value, page=1) for metric, values in [
        ('Opening', [-50, -60]), ('Adjustment A', [5, 14]),
        ('Adjustment B', [None, 11]), ('Closing', [-45, -35])]
        for period, value in zip(['FY2023', 'FY2024'], values) if value is not None]
    table = ExtractedTable(table_id='source', page=1, headers=['Metric', '2023', '2024'],
        column_periods=[None, 'FY2023', 'FY2024'], confidence=1,
        rows=[TableRow(page=1, cells=[m, *v]) for m,v in [
            ('Opening',['(50)','(60)']), ('Adjustment A',['5','14']),
            ('Adjustment B',['—','11']), ('Closing',['(45)','(35)'])]])
    result = SimpleNamespace(document=SimpleNamespace(pages=[SimpleNamespace(page_number=1,tables=[table])]))
    return items, table, result


def test_source_table_layout_keeps_negative_rows_and_sparse_source_dash():
    items, table, result = source_fixture()
    before = deepcopy(items)
    assert compact_source_table(items)
    group = [o for o in items if o.metric_original == 'Adjustment B']
    assert literal_empty_source_cell(group, 'FY2023*', result) == '—'
    assert literal_empty_source_cell(group, 'FY2022', result) is None
    assert items == before and table.rows[2].cells[1] == '—'


@pytest.mark.parametrize('fault', ['conflict', 'currency', 'table', 'period'])
def test_compact_table_rejects_incompatible_or_conflicting_sources(fault):
    items, _, _ = source_fixture()
    if fault == 'conflict':
        extra = items[0].model_copy(update={'id':'conflicting', 'value':999})
        items.append(extra)
    if fault == 'currency': items[0].currency='USD'
    if fault == 'table':
        for o in items:
            if o.metric_original=='Closing': o.evidence[0].table_id='other'
    if fault == 'period': items[0].period=None
    assert not compact_source_table(items)


def test_literal_empty_cell_requires_unique_row_period_and_resolved_alignment():
    items, table, result = source_fixture()
    group=[o for o in items if o.metric_original=='Adjustment B']
    table.rows[2].alignment_status='ambiguous'
    assert literal_empty_source_cell(group,'FY2023',result) is None
    table.rows[2].alignment_status='resolved'
    table.rows.append(TableRow(page=1,cells=['Adjustment B','N/A','11']))
    assert literal_empty_source_cell(group,'FY2023',result) is None


def test_agenda_uses_neutral_authored_topic_not_directional_takeaway():
    topic=_topic('series');topic.title='Operating performance and constraints'
    result=SimpleNamespace(presentation_topics=PresentationTopicSelection(topics=[topic]))
    slide=PresentationSlide(id='page',slide_type='analysis',title='Output rose then fell across several periods.',
        section_title='Output rose then fell across several periods.',theme_id=topic.id)
    assert section_heading(result,slide)==topic.title
