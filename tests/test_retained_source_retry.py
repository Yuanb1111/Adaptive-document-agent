"""Local publication fixes preserve the validated deck and require fresh review."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_analysis_review import review_retained_analysis, review_complete
from adaptive_document_agent.agent.retained_source_retry import repair_retained_source_copy
from tests.test_retained_analysis_v216 import gateway
from tests.test_retained_source_citations import fixture


def rejected_checkpoint():
    result, _, selection = fixture()
    other = 'accepted-sibling'
    result.insights.append(result.insights[0].model_copy(update={'id': other}))
    selection.decisions.append(selection.decisions[0].model_copy(deep=True, update={'insight_id': other}))
    selection.ordered_insight_ids.append(other)
    retained.select_retained_analysis(gateway([selection.model_dump(),
        dict(accepted=True, reason='Synthetic source-bound selection.')]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    slides = [s for s in result.presentation_plan.slides if s.slide_type == 'analysis']
    with pytest.raises(ValueError, match='evidence review rejected'):
        review_retained_analysis(gateway([dict(verdicts=[dict(slide_id=s.id,
            accepted=s.insight_ids == [other], reason='Clarify source attribution.') for s in slides],
            omissions_accepted=True, omission_reason='Synthetic complete selection.')]), result)
    result.failed_stage = 'presentation_coverage'
    result.failure_details = dict(component='PresentationCoverage')
    return result, selection.ordered_insight_ids[0]


def test_direct_source_fix_freezes_good_pages_data_and_selection_without_final_approval():
    previous, iid = rejected_checkpoint()
    diagnostic = 'A prior local correction failed at an attributive direction token.'
    previous.failure_details['message'] = diagnostic
    target = next(s for s in previous.presentation_plan.slides if s.insight_ids == [iid])
    target.bullets.append('Separate source coverage remains available.')
    target.bullet_observation_ids.append(list(target.observation_ids))
    # This is a post-review native binding; regenerate the rejected source
    # verdict for the current complete presentation context.
    from adaptive_document_agent.agent.retained_analysis_review import review_context, REVIEW_CODE
    import json
    last = next(w for w in reversed(previous.validation_warnings) if w.code == REVIEW_CODE)
    record = json.loads(last.message)
    record['fingerprint'] = retained.fingerprint(review_context(previous))
    last.message = json.dumps(record)
    current = previous.model_copy(deep=True)
    before = deepcopy(current)
    original = retained.selected_record(previous)['selection']['decisions'][0]['page']['message']
    mock = gateway([dict(edits={iid: dict(message=[dict(before=original,
        after='The source reports revenue with its period labels.')])})])
    repair_retained_source_copy(mock, current, previous)
    assert previous == before
    for field in ('document', 'observations', 'analysis_plan', 'analysis_results', 'insights', 'charts'):
        assert getattr(current, field) == getattr(before, field)
    assert retained.selected_record(current)['selection']['ordered_insight_ids'] == [iid, 'accepted-sibling']
    accepted = lambda r: next(s for s in r.presentation_plan.slides if s.insight_ids == ['accepted-sibling'])
    assert accepted(current) == accepted(before)
    fixed = next(s for s in current.presentation_plan.slides if s.insight_ids == [iid])
    assert fixed.message == 'The source reports revenue with its period labels.'
    assert fixed.bullets[1:] == target.bullets[1:]
    assert fixed.bullet_observation_ids == target.bullet_observation_ids
    assert [row['operation'] for row in mock.usage] == ['RetainedPageRevisions']
    from adaptive_document_agent.utils.record_encoding import decode_records
    source_packet = mock.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]
    assert decode_records(json.loads(source_packet))['earlier_review_questions'][iid] == [diagnostic]
    assert not review_complete(current)


def test_local_source_fix_cannot_introduce_ineligible_companion_rows(monkeypatch):
    from adaptive_document_agent.agent import retained_page_revision
    previous, iid = rejected_checkpoint()
    page = retained.RetainedAnalysisSelection.model_validate(
        retained.selected_record(previous)['selection']).decisions[0].page
    page.companion_ids.append('new-numeric-row')
    monkeypatch.setattr(retained_page_revision, 'revise_retained_pages', lambda *_, **_kw: {iid: page})
    with pytest.raises(ValueError):
        repair_retained_source_copy(None, previous.model_copy(deep=True), previous)


def test_failed_writer_transport_stays_out_of_source_questions():
    import json
    from adaptive_document_agent.utils.record_encoding import decode_records
    previous, iid = rejected_checkpoint()
    previous.failure_details.update(error_type='LLMStructuredOutputError', message='Bounded response failed schema validation')
    current = previous.model_copy(deep=True)
    mock = gateway([dict(edits={iid: dict(message=[dict(span_id='copy-0', after='The source reports revenue.')])}),
                    dict(edits={iid: dict(message=[dict(span_id='copy-0', after='Revenue is reported.')])})])
    repair_retained_source_copy(mock, current, previous)
    body = mock.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]
    assert decode_records(json.loads(body))['earlier_review_questions'][iid] == ['Original-page review failed']
    audit = next(w for w in reversed(current.validation_warnings) if w.code == 'retained_selection_retry_feedback')
    assert json.loads(audit.message)['rejected']['diagnostic'] == previous.failure_details['message']


def test_fix_rewrites_published_source_bullet_and_removes_repeated_main_copy():
    import json
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
    from adaptive_document_agent.utils.record_encoding import decode_records
    result, _, selection = fixture()
    iid = selection.ordered_insight_ids[0]
    original = selection.decisions[0].page
    repeated = 'The source describes payment delays.'
    original.message += ' ' + repeated
    proof = 'Management identified payment delays in the export business.'
    result.document.pages[0].text += '\n' + proof
    item = QualifiedSourceCopy(scope='export business', description='describes payment delays',
                                 quote={'page': 234, 'text': proof})
    original.source_context.append(item)
    retained.select_retained_analysis(gateway([selection.model_dump(), dict(
        accepted=True, reason='The selected finding and proof match the source.')]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    slide = next(s for s in result.presentation_plan.slides if s.slide_type == 'analysis')
    with pytest.raises(ValueError, match='evidence review rejected'):
        review_retained_analysis(gateway([dict(verdicts=[dict(slide_id=slide.id, accepted=False,
            reason='Name the speaker in the explanatory bullet and remove the duplicate in the main text.')],
            omissions_accepted=True, omission_reason='Selection accepted.')]), result)
    before = slide.model_copy(deep=True)
    revised = 'reports that management identified payment delays'
    llm = gateway([dict(edits={iid: dict(message=[dict(before=repeated, after='')],
                                        source_context_descriptions={'context-0': revised})})])
    repair_retained_source_copy(llm, result)
    packet = decode_records(json.loads(llm.client.calls[0][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
    assert packet['pages_to_correct'][iid]['published_source_descriptions'] == {'context-0': before.bullets[1]}
    assert repeated not in slide.message and revised in slide.bullets[1] and len(slide.bullets) == 2
    assert slide.bullet_observation_ids == before.bullet_observation_ids and slide.source_pages == before.source_pages
    stored = retained.selected_record(result)['selection']['decisions'][0]['page']['source_context'][0]
    assert stored['description'] == revised and stored['quote'] == {'page': 234, 'text': proof}
    assert stored['scope'] == item.scope and not review_complete(result)


def test_native_preparation_preserves_exact_source_authored_qualifications_without_approving_them():
    from adaptive_document_agent.services.presentation_claim_evidence import prepare_presentation_claims
    from adaptive_document_agent.services.pipeline_completion import require_topic_coverage
    result, _, selection = fixture()
    qualification = ('During the Track Record Period, the source says the proportion '
                     'of legacy revenue increased.')
    result.document.pages[0].text += '\n' + qualification
    selection.decisions[0].page.message = qualification
    from adaptive_document_agent.models.executive_brief import BriefQuote
    selection.decisions[0].page.context_evidence = [BriefQuote(page=234, text=qualification)]
    retained.select_retained_analysis(gateway([selection.model_dump(),
        dict(accepted=True, reason='Synthetic source selection.')]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    slide = next(s for s in result.presentation_plan.slides if s.slide_type == 'analysis')
    before = slide.model_copy(deep=True)
    prepare_presentation_claims(result)
    prepare_presentation_claims(result)
    assert slide.message == qualification and slide.bullets == before.bullets
    assert slide.observation_ids == before.observation_ids
    with pytest.raises(ValueError, match='Retained-analysis evidence'):
        require_topic_coverage(result)


def test_only_a_fresh_independent_review_can_authorize_another_bounded_source_edit():
    from adaptive_document_agent.agent.retained_selection_feedback import can_retry_source_review, retain_selection_feedback
    previous, _ = rejected_checkpoint()
    assert can_retry_source_review(previous)
    previous.validation_warnings.append(retain_selection_feedback(previous))
    assert not can_retry_source_review(previous)
    slides = [s for s in previous.presentation_plan.slides if s.slide_type == 'analysis']
    with pytest.raises(ValueError, match='evidence review rejected'):
        review_retained_analysis(gateway([dict(verdicts=[dict(slide_id=s.id, accepted=False,
            reason='Fresh source review found an unresolved qualification.') for s in slides],
            omissions_accepted=True, omission_reason='Synthetic material selection.')]), previous)
    assert can_retry_source_review(previous)
    assert not review_complete(previous)
