"""A source footer is reviewable provenance, never semantic approval."""
import json
from copy import deepcopy

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_page_sources import planned_source_citations
from adaptive_document_agent.agent.retained_selection_coverage import review_selection_coverage
from adaptive_document_agent.models import SourceEvidence, DocumentPage
from adaptive_document_agent.services.source_citations import source_footer
from adaptive_document_agent.utils.record_encoding import decode_records
from tests.test_retained_analysis_v216 import _linked_result, gateway


def fixture():
    result = _linked_result()
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Source table')])]
    iid = result.insights[0].id
    selection = retained.RetainedAnalysisSelection(decisions=[dict(insight_id=iid, decision='include',
        reason='Source trajectory.', page=dict(title='Revenue', message='The source reports revenue.',
                                              companion_ids=[]))], ordered_insight_ids=[iid])
    context = retained.selection_context(result, source_authoring=True)
    return result, context, selection


def test_review_packet_and_compiled_slide_use_same_literal_source_footer():
    from adaptive_document_agent.services.pptx_export import _source_footer
    result, context, selection = fixture()
    before = deepcopy(result.observations)
    mock = gateway([selection.model_dump(), dict(accepted=True, reason='Synthetic review')])
    retained.select_retained_analysis(mock, result)
    wire = mock.client.calls[-1][-1]['content']
    payload = decode_records(json.loads(wire.split('\n', 1)[1].rsplit('\n', 1)[0]))
    citation, = payload['planned_source_citations']
    plan = retained.compile_retained_analysis(result)
    slide, = (s for s in plan.slides if s.slide_type == 'analysis')
    assert citation['source_pages'] == slide.source_pages == [234]
    assert citation['footer'] == _source_footer(slide.source_pages) == 'Source: Document disclosures (p. 234)'
    assert citation['observation_ids'] == slide.observation_ids
    assert result.observations == before
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)


def test_citation_includes_bound_companion_evidence_and_changes_review_fingerprint():
    result, context, selection = fixture()
    companion = result.observations[0].model_copy(deep=True)
    companion.table_id = result.observations[0].effective_table_id
    companion.id = 'companion'
    companion.evidence = [SourceEvidence(page=235, text='Additional source cell',
                                       extraction_method='digital_table', confidence=1)]
    result.observations.append(companion)
    result.document.pages.append(DocumentPage(page_number=235, text='Additional source cell'))
    context['source_rows'].append(dict(id=companion.id, table_id=companion.effective_table_id))
    selection.decisions[0].page.companion_ids = [companion.id]
    citation, = planned_source_citations(selection, context, result)
    assert citation['source_pages'] == [234, 235]
    assert citation['footer'].endswith('(p. 234-235)')
    records = []
    for page in (235, 236):
        companion.evidence[0].page = page
        if page == 236:
            result.document.pages.append(DocumentPage(page_number=236, text='Moved source cell'))
        review_selection_coverage(gateway([dict(accepted=True, reason='Synthetic review')]), context, selection, result)
        records.append(json.loads(result.validation_warnings[-1].message)['input_fingerprint'])
    assert records[0] != records[1]


@pytest.mark.parametrize('fault', ['unknown_row', 'foreign_companion', 'missing_page', 'missing_primary'])
def test_invalid_bindings_cannot_acquire_a_planned_citation(fault):
    result, context, selection = fixture()
    if fault == 'unknown_row':
        selection.decisions[0].page.companion_ids = ['not-an-observation']
    elif fault == 'foreign_companion':
        other = result.observations[0].model_copy(update={'id': 'foreign'})
        result.observations.append(other)
        selection.decisions[0].page.companion_ids = ['foreign']
    elif fault == 'missing_page':
        result.document.pages.clear()
    else:
        context['findings'][0]['observation_ids'] = []
    assert not planned_source_citations(selection, context, result)


def test_source_attribution_rejection_still_blocks_even_with_page_citation():
    result, context, selection = fixture()
    assert planned_source_citations(selection, context, result)
    reply = dict(accepted=False, reason='Attribution is unsupported.',
                 page_issues=[dict(insight_id=selection.ordered_insight_ids[0],
                                   reason='The statement loses its management attribution.')])
    with pytest.raises(ValueError, match='management attribution'):
        review_selection_coverage(gateway([reply]), context, selection, result)
    audit = json.loads(result.validation_warnings[-1].message)
    assert not audit['review']['accepted'] and not audit['final_presentation_approval']


def test_empty_pages_do_not_invent_a_source_reference():
    assert source_footer([]) == 'Source: Document disclosures (page references not available)'
