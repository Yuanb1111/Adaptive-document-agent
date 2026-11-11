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
