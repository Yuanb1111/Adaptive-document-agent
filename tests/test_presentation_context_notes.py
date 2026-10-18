"""Context notes retain source qualifiers and distinguish source from display units."""

import pytest

from adaptive_document_agent.models import DocumentPage, ExtractedTable, PresentationTheme
from adaptive_document_agent.services.presentation_context_notes import slide_context_notes
from tests.test_presentation_key_figures import _result


def context_result(caveats):
    result = _result()
    chart, slide = result.charts[0], result.presentation_plan.slides[0]
    slide.theme_id = 'selected'
    result.presentation_plan.themes = [PresentationTheme(
        id='selected', title='Selected measures', question='What changed?', rationale='Source evidence',
        chart_ids=[chart.id], caveats=caveats)]
    return result, slide, chart, {o.id: o for o in result.observations}


@pytest.mark.parametrize('caveat', [
    'Amounts are presented in RMB thousands.',
    'Amounts are shown in RMB in thousands; estimates exclude exceptional items.',
    'Values are reported in RMB thousands. Interim values are provisional.',
])
def test_matching_source_unit_statement_is_explicit_without_losing_conditions(caveat):
    result, slide, chart, index = context_result([caveat])
    for oid in chart.observation_ids:
        item = index[oid]
        item.raw_unit, item.unit, item.currency, item.unit_scale = 'RMB in thousands', 'currency', 'RMB', 1000
        item.value *= 1_000_000
    before = result.model_dump()
    assert slide_context_notes(result, slide, [chart], index, definitions=[]) == [
        'Source ' + caveat[0].lower() + caveat[1:]]
    assert result.model_dump() == before


@pytest.mark.parametrize('defect', ['different_unit', 'missing_source', 'extra_scope', 'missing_unit'])
def test_units_are_not_reinterpreted_without_a_unique_literal_source_match(defect):
    caveat = 'Amounts are presented in RMB thousands.'
    if defect == 'extra_scope':
        caveat = 'Selected amounts are presented in RMB thousands.'
    result, slide, chart, index = context_result([caveat])
    for oid in chart.observation_ids:
        index[oid].raw_unit = 'RMB in thousands'
    if defect == 'different_unit':
        index[chart.observation_ids[-1]].raw_unit = 'USD in thousands'
    elif defect == 'missing_source':
        index[chart.observation_ids[-1]].evidence = []
    elif defect == 'missing_unit':
        index[chart.observation_ids[-1]].raw_unit = None
    assert slide_context_notes(result, slide, [chart], index, definitions=[]) == [caveat]


def test_source_definition_wins_over_typographic_duplicate_but_keeps_extra_qualifiers():
    quote = 'Ancillary services include training, maintenance and technical services.'
    extra = quote + ' Only directly billed services are included.'
    paraphrase = 'Ancillary services comprise maintenance, technical services and training.'
    result, slide, chart, index = context_result(['(1)  ' + quote.upper(), extra, paraphrase])
    result.document.pages = [DocumentPage(page_number=2, text='Notes:\n(1) ' + quote,
        tables=[ExtractedTable(table_id='table-0', page=2,
                               raw_body_lines=['Ancillary services(1) 10 20'])])]
    for oid in chart.observation_ids:
        evidence = index[oid].evidence[0]
        evidence.row_label, evidence.table_id = 'Ancillary services', 'table-0'
    before = result.model_dump()
    assert slide_context_notes(result, slide, [chart], index, definitions=[]) == [quote, extra, paraphrase]
    assert result.model_dump() == before
