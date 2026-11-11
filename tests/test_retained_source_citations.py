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


def test_compiler_and_export_validation_preserve_literal_related_context(monkeypatch):
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    from adaptive_document_agent.agent.audit_source_layout import audit_source_page
    from adaptive_document_agent.models.executive_brief import BriefQuote
    result, _, selection = fixture()
    extra = DocumentPage(page_number=235, text='Related exposure qualifies this reported balance.')
    result.document.pages.append(extra)
    original_sources = retained.page_sources

    def sources(current, linked):
        context = original_sources(current, linked)
        context['source_pages'].append(audit_source_page(current.document.pages[-1]))
        return context

    monkeypatch.setattr(retained, 'page_sources', sources)
    selection.decisions[0].page.context_evidence = [BriefQuote(page=235, text=extra.text)]
    retained.select_retained_analysis(gateway([selection.model_dump(),
        dict(accepted=True, reason='Synthetic cross-measure source review.')]), result)
    plan = retained.compile_retained_analysis(result)
    slide, = (s for s in plan.slides if s.slide_type == 'analysis')
    assert slide.source_pages == plan.themes[0].source_pages == [234, 235]
    PresentationPlanValidator().validate(plan, result)
    slide.source_pages.append(236)
    with pytest.raises(ValueError, match='not supported by its retained references'):
        PresentationPlanValidator().validate(plan, result)
    slide.source_pages.remove(236)
    result.document.pages[-1].text = 'The original qualification changed.'
    with pytest.raises(ValueError, match='stale source bindings'):
        PresentationPlanValidator().validate(plan, result)


@pytest.mark.parametrize('matching_pages', [[235], [235, 236], []])
def test_quote_page_recovery_preserves_evidence_and_allows_bounded_revision(monkeypatch, matching_pages):
    from adaptive_document_agent.agent.retained_selection_feedback import retain_selection_feedback
    from adaptive_document_agent.models import ValidationIssue

    result, _, proposal = fixture()
    iid = proposal.ordered_insight_ids[0]
    quote = 'Related exposure qualifies this reported balance.'
    result.document.pages.append(DocumentPage(page_number=237, text=quote))  # Not supplied.
    for page in (235, 236):
        result.document.pages.append(DocumentPage(page_number=page,
            text=quote if page in matching_pages else 'Different source passage.'))
    other_id = 'other-retained-page'
    result.insights.append(result.insights[0].model_copy(update={'id': other_id}))
    original_sources = retained.page_sources

    def sources(current, linked):
        context = original_sources(current, linked)
        context['source_pages'].extend(dict(page=p.page_number, text=p.text)
            for p in current.document.pages if p.page_number in (235, 236))
        return context

    monkeypatch.setattr(retained, 'page_sources', sources)
    draft = proposal.model_dump(exclude_none=True)
    draft['decisions'][0]['page']['context_evidence'] = [dict(page=234, text=quote)]
    draft['decisions'].append(dict(insight_id=other_id, decision='include', reason='Other finding.',
        page=dict(title='Other context', message='Revenue is reported.', companion_ids=[], context_evidence=[])))
    draft['ordered_insight_ids'].append(other_id)
    result.failed_stage = 'presentation_selection'
    result.failure_details = dict(component='RetainedAnalysisSelection')
    result.validation_warnings.append(ValidationIssue(code='retained_page_draft_rejected', stage='presentation',
        message=json.dumps(dict(rejected_draft=draft, row_ids={}, diagnostic='The quote uses the wrong page.'))))
    result.validation_warnings.append(retain_selection_feedback(result))
    source_before = result.model_dump(include={'document', 'observations', 'insights', 'analysis_results'})
    accepted = dict(accepted=True, reason='Synthetic coverage only.')
    corrected = deepcopy(draft['decisions'][0]['page'])
    corrected['context_evidence'] = [dict(page=235, text=quote)] if matching_pages else []
    repaired_by_model = len(matching_pages) != 1
    mock = gateway([accepted, dict(pages={iid: corrected}), accepted] if repaired_by_model else [accepted])
    retained.select_retained_analysis(mock, result)

    coverage = decode_records(json.loads(mock.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]))
    citations = {row['insight_id']: row['source_pages'] for row in coverage['planned_source_citations']}
    assert citations[other_id] == [234]
    if repaired_by_model:
        assert iid not in citations
        assert 'Quote 1 does not bind to page 234' in coverage['copy_validation_errors'][0]
        wire = mock.client.calls[1][-1]['content']
        patch_request = decode_records(json.loads(wire.split('\n', 1)[1].rsplit('\n', 1)[0]))
        assert set(patch_request['pages_to_correct']) == {iid}
    else:
        assert citations[iid] == [234, 235]
        assert not coverage['copy_validation_errors']
        assert retained.selected_record(result)['context_page_corrections'] == [dict(
            insight_id=iid, quote_index=0, original_page=234, source_page=235)]
    record = retained.selected_record(result)['selection']
    assert record['ordered_insight_ids'] == draft['ordered_insight_ids']
    assert record['decisions'][0]['page'] == corrected
    assert record['decisions'][1] == draft['decisions'][1]
    assert result.model_dump(include=set(source_before)) == source_before
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)


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


def test_writer_and_reviewer_receive_only_explicit_row_assurance():
    from adaptive_document_agent.agent.retained_page_sources import writer_context

    result, _, selection = fixture()
    result.observations[0].audited_status = 'unaudited'
    result.observations[1].audited_status = 'unknown'
    context = retained.selection_context(result, source_authoring=True)
    _, aliases = writer_context(context)
    observation_id = result.observations[0].id
    alias = next(ref for ref, oid in aliases.items() if oid == observation_id)
    mock = gateway([selection.model_dump(), dict(accepted=True, reason='Synthetic review')])
    retained.select_retained_analysis(mock, result)
    packets = [decode_records(json.loads(call[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]))
               for call in mock.client.calls]
    assert packets[0]['source_row_assurance'] == {alias: 'unaudited'}
    assert packets[1]['source_row_assurance'] == {observation_id: 'unaudited'}
    citation, = packets[1]['planned_source_citations']
    assert citation['bound_periods'] == sorted({o.period for o in result.observations})
    assert {o['observation_id']: o['audited_status'] for o in citation['bound_assurance']} == {
        o.id: o.audited_status for o in result.observations if o.id in citation['observation_ids']
    }
    assert retained.selection_context(result, source_authoring=True) == context


@pytest.mark.parametrize('period,status,accepted', [
    ('6M2023', 'unaudited', True), ('6M2024', 'unaudited', False),
    ('6M2024', 'audited', False), ('6M2025', 'unaudited', False),
])
def test_explicit_assurance_requires_a_matching_bound_period(period, status, accepted):
    from adaptive_document_agent.agent.retained_page_sources import _check_explicit_period_assurance
    from tests.test_topic_coverage_review import _observation

    rows = [_observation('Loss', '6M2023', 100).model_copy(update={'audited_status': 'unaudited'}),
            _observation('Loss', '6M2024', 120)]
    copy = f'Loss in {period} ({status}) was reported.'
    if accepted:
        _check_explicit_period_assurance(copy, rows)
    else:
        with pytest.raises(ValueError, match=f'{period} has no bound row explicitly marked {status}'):
            _check_explicit_period_assurance(copy, rows)


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
