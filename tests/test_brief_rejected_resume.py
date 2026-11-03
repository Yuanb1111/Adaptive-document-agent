"""Explicit retries keep unchanged source-valid candidates and repair fresh rejections."""
import json

import pytest

from adaptive_document_agent.agent.brief_review_checkpoint import save_checks, context_key
from adaptive_document_agent.agent.brief_review_resume import resume_brief_review
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem
from tests.test_executive_brief import result_for


def fixture(monkeypatch, *, accepted=True):
    from adaptive_document_agent.agent import brief_meaning_review
    source = 'Revenue was 12 in 2024. Its scope excludes pilot customers. Costs were 8 in 2024.'
    result = result_for([source])
    candidate = ExecutiveBrief(items=[ExecutiveBriefItem(label=label, text=text,
        evidence=[dict(page=1, text=source)]) for label, text in [
            ('Revenue', 'Revenue was 12 in 2024.'), ('Costs', 'Costs were 8 in 2024.')]])
    corrected = 'Revenue was 12 in 2024, excluding pilot customers.'
    context = dict(output_limits=dict(maximum_findings=5), selected_analysis_topics=[])
    save_checks(result, context_key(candidate, context, result), candidate,
        {0: ['Missing the quoted scope qualification.'], 1: []}, {}, context)
    reviewed = []
    def review(brief):
        reviewed.append(brief.model_copy(deep=True))
        return {} if accepted and brief.items[0].text == corrected else {
            0: ['Missing the quoted scope qualification.']}
    monkeypatch.setattr(brief_meaning_review, 'meaning_validator', lambda *args, **kwargs: review)
    class Gateway:
        def __init__(self):
            self.calls = []
        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(schema)
            assert set(schema.model_fields) == {'item_0'}
            return schema.model_validate(dict(item_0=dict(text=corrected)))
    return result, candidate, Gateway(), reviewed


def test_rejected_candidate_receives_only_a_targeted_patch_and_fresh_complete_review(monkeypatch):
    result, candidate, gateway, reviewed = fixture(monkeypatch)
    corrected = resume_brief_review(gateway, result)
    assert corrected.items[1] == candidate.items[1]
    assert corrected.items[0].evidence == candidate.items[0].evidence
    assert corrected.items[0].text == 'Revenue was 12 in 2024, excluding pilot customers.'
    assert len(gateway.calls) == 1 and len(reviewed) >= 2
    assert reviewed[-1] == corrected
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['outcome'] == 'repaired' and audit['discarded_indices'] == []


def test_stale_source_context_does_not_reuse_or_patch_a_saved_candidate(monkeypatch):
    result, _, gateway, reviewed = fixture(monkeypatch)
    result.profile.analysis_focus = 'A different scope'
    assert resume_brief_review(gateway, result) is None
    assert not gateway.calls and not reviewed


def test_rejected_correction_cannot_fall_back_to_silent_full_regeneration(monkeypatch):
    result, _, gateway, reviewed = fixture(monkeypatch, accepted=False)
    with pytest.raises(ValueError, match='Saved executive briefing correction failed'):
        resume_brief_review(gateway, result)
    assert len(gateway.calls) == 1 and reviewed
    assert json.loads(result.validation_warnings[-1].message)['outcome'] == 'rejected'


@pytest.mark.parametrize('previously_accepted', [False, True])
def test_title_or_feedback_changes_can_recover_only_an_unverified_draft(monkeypatch, previously_accepted):
    from adaptive_document_agent.agent.brief_rejected_resume import source_matched_candidate
    from adaptive_document_agent.models import PresentationPlan
    result, candidate, gateway, reviewed = fixture(monkeypatch)
    record = json.loads(result.validation_warnings[-1].message)
    if previously_accepted:
        record['checked'] = {str(i): [] for i in range(len(candidate.items))}
        record['semantic_approval'] = True
        result.validation_warnings[-1].message = json.dumps(record)
    context = record['source_context']
    result.presentation_plan = PresentationPlan(title='Changed report title')
    context = {**context, 'previous_rejected_brief': {'issues': ['Untrusted feedback changed']},
               'source_native_quantity_options': ['Rebuilt optional spelling hints']}
    assert source_matched_candidate(result, context,
        {1: result.document.pages[0].text}, []) == candidate
    assert not gateway.calls and not reviewed  # A draft is not approval.
    assert source_matched_candidate(result, {**context, 'user_focus': 'Changed focus'},
        {1: result.document.pages[0].text}, []) is None


def test_recovered_draft_still_fails_the_normal_independent_review_gate(monkeypatch):
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    from tests.test_executive_brief import gateway
    result, candidate, _, _ = fixture(monkeypatch)
    g, client = gateway([dict(item_0=candidate.items[0].model_dump(mode='json'))])
    with pytest.raises(ValueError, match='Still missing scope'):
        generate_with_item_repair(g, [dict(role='system', content='Use original evidence.')],
            result=result, excerpts={1: result.document.pages[0].text}, topics=[], source_context={},
            initial_brief=candidate, semantic_validator=lambda brief: {0: ['Still missing scope']})
    assert len(client.editorial_calls) == 1  # Only a patch, no replacement writer.


def test_json_round_trip_of_page_range_tuples_does_not_discard_the_candidate(monkeypatch):
    from adaptive_document_agent.agent.brief_rejected_resume import source_matched_candidate
    result, candidate, _, _ = fixture(monkeypatch)
    record = json.loads(result.validation_warnings[-1].message)
    record['source_context']['analysis_scope'] = [[1, 1]]
    result.validation_warnings[-1].message = json.dumps(record)
    context = {**record['source_context'], 'analysis_scope': [(1, 1)]}
    excerpts = {1: result.document.pages[0].text}
    assert source_matched_candidate(result, context, excerpts, []) == candidate
    context['analysis_scope'] = [(1, 2)]
    assert source_matched_candidate(result, context, excerpts, []) is None
