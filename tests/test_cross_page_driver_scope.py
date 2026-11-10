"""Narrative ownership must be readable across page boundaries at every review."""
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_page_revision import revise_retained_pages
from adaptive_document_agent.agent.retained_page_sources import (
    planned_source_citations, source_row_assurance, writer_context,
)
from adaptive_document_agent.agent.retained_selection_coverage import review_selection_coverage
from adaptive_document_agent.models import DocumentPage, PipelineResult, SourceEvidence
from adaptive_document_agent.utils.record_encoding import decode_records
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway


def _payload(call):
    return decode_records(json.loads(call[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]))


@pytest.mark.parametrize('legacy_driver', [False, True])
def test_writer_revision_review_and_citation_keep_the_paragraph_opening(legacy_driver):
    result, _, selection = fixture()
    insight = result.insights[0]
    result.document.pages.extend([
        DocumentPage(page_number=240, text='In FY2023, service activity reflected'),
        DocumentPage(page_number=241, text='longer customer contracts and renewals.\nIn FY2024, demand changed.'),
        DocumentPage(page_number=242, text='Further source qualifications.'),
    ])
    insight.driver_quote = 'longer customer contracts and renewals.'
    insight.driver_source_page = 241
    if not legacy_driver:
        insight.evidence.append(SourceEvidence(page=241, text=insight.driver_quote,
            extraction_method='source_text_context', confidence=1))
    original = deepcopy((result.insights, result.observations, result.document))
    context = retained.selection_context(result, source_authoring=True)
    sources = {p['page']: p['text'] for p in context['source_pages']}
    assert sources[240].startswith('In FY2023')
    assert sources[241].startswith(insight.driver_quote)
    assert sources[242] == 'Further source qualifications.'
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    mock = gateway([dict(pages={insight.id: selection.decisions[0].page.model_dump()})])
    revise_retained_pages(mock, result, packet, aliases, selection.model_dump(),
                         {insight.id: ['Check the paragraph period in its full context.']},
                         earlier_issues={insight.id: ['Retain the previously corrected limitation.'],
                                         'unrequested-page': ['No edit permission.']})
    correction = _payload(mock.client.calls[0])
    assert correction['earlier_review_questions'] == {
        insight.id: ['Retain the previously corrected limitation.']}
    assert {p['page']: p['text'] for p in correction['source_pages']} == sources
    assert correction['pages_to_correct'][insight.id]['source_page_numbers'] == sorted(sources)
    calculations = correction['pages_to_correct'][insight.id]['bound_calculations']
    assert calculations
    assert all(set(c['observation_ids']) <= {o.id for o in result.observations} for c in calculations)
    assert all(c['fact_type'] == 'calculated_result' for c in calculations)
    review_gateway = gateway([dict(accepted=True, reason='Synthetic packet protocol check.')])
    review_selection_coverage(review_gateway, context, selection, result)
    review = _payload(review_gateway.client.calls[0])
    assert review['source_pages'] == context['source_pages']
    citation, = planned_source_citations(selection, context, result)
    assert citation['source_pages'] == [234, 240, 241, 242]
    assert (result.insights, result.observations, result.document) == original
    retained.select_retained_analysis(gateway([selection.model_dump(),
        dict(accepted=True, reason='Synthetic compilation protocol check.')]), result)
    plan = retained.compile_retained_analysis(result)
    slide = next(s for s in plan.slides if s.slide_type == 'analysis')
    assert slide.source_pages == citation['source_pages']
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    slide.source_pages.append(239)
    with pytest.raises(ValueError, match='not supported by its retained references'):
        PresentationPlanValidator().validate(plan, result)
    slide.source_pages.remove(239)
    # Legacy direct citations are still valid. Context pages add provenance,
    # never new numeric inputs or an exemption from source validation.
    direct = sorted({e.page for e in insight.evidence}
                    | {e.page for o in result.observations for e in o.evidence})
    for theme in plan.themes:
        theme.source_pages = direct
    slide.source_pages = direct
    PresentationPlanValidator().validate(plan, result)
    review_selection_coverage(gateway([dict(accepted=True, reason='Synthetic packet check.')]), context, selection, result)
    first = json.loads(result.validation_warnings[-1].message)['input_fingerprint']
    result.document.pages[1].text = 'In FY2022, service activity reflected'
    fresh = retained.selection_context(result, source_authoring=True)
    review_selection_coverage(gateway([dict(accepted=True, reason='Synthetic packet check.')]), fresh, selection, result)
    assert json.loads(result.validation_warnings[-1].message)['input_fingerprint'] != first


def test_missing_driver_page_cannot_be_replaced_by_its_neighbor():
    result, _, selection = fixture()
    insight = result.insights[0]
    insight.driver_source_page = 235
    insight.driver_quote = 'A quote missing from the retained document.'
    context = retained.selection_context(result, source_authoring=True)
    assert not planned_source_citations(selection, context, result)


def test_private_242_checkpoint_preserves_cross_page_scope_without_licensing_prose_amounts():
    path = os.getenv('CROSS_PAGE_DIAGNOSTIC')
    if not path:
        pytest.skip('Set CROSS_PAGE_DIAGNOSTIC to the private .242 JSON for checkpoint replay.')
    result = PipelineResult.model_validate_json(Path(path).read_bytes())
    before = result.model_dump(include={'document', 'observations', 'insights', 'analysis_results'})
    context = retained.selection_context(result, source_authoring=True)
    sources = {p['page']: p['text'] for p in context['source_pages']}
    assert 'Net cash from operating activities was RMB6.4 million in 2021' in sources[340]
    assert 'inventories of RMB33.0 million' in sources[341]
    rejected = json.loads(next(w.message for w in reversed(result.validation_warnings)
                              if w.code == 'retained_page_draft_rejected'))
    selection = retained.RetainedAnalysisSelection.model_validate(rejected['rejected_draft'])
    for decision in selection.decisions:
        if decision.page:
            decision.page.companion_ids = [rejected['row_ids'].get(k, k) for k in decision.page.companion_ids]
    target = next(i for i in result.insights if i.driver_source_page == 341 and 'RMB33.0' in i.driver_quote)
    citation = next(c for c in planned_source_citations(selection, context, result) if c['insight_id'] == target.id)
    assert {339, 340, 341} <= set(citation['source_pages'])
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    decision = next(d for d in selection.decisions if d.insight_id == target.id)
    mock = gateway([dict(pages={target.id: decision.page.model_dump()})])
    revise_retained_pages(mock, result, packet, aliases, selection.model_dump(), {target.id: ['Verify period.']})
    assert {339, 340, 341} <= {p['page'] for p in _payload(mock.client.calls[0])['source_pages']}
    from adaptive_document_agent.agent.retained_page_sources import page_bindings
    primary = set(next(f['observation_ids'] for f in context['findings'] if f['insight']['id'] == target.id))
    unsupported = decision.page.model_copy(update={'message': 'Inventories were RMB33.0 million in FY2021.'})
    with pytest.raises(ValueError, match='outside its bound evidence'):
        page_bindings(unsupported, target, primary, context, result)
    assert result.model_dump(include=set(before)) == before
