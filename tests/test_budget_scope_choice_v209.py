"""A model chooses priorities; Python binds exactly one feasible measured scope."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.presentation_budget_scope import (
    PhysicalBudgetScopeChoice, bind_scope_choice, choose_whole_topic_scope,
)
from adaptive_document_agent.models import PresentationTopic, PresentationTopicSelection
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError


def case():
    original = PresentationTopicSelection(topics=[
        PresentationTopic(id='first', title='First question', question='First?', rationale='First source priority.',
            series_ids=['a', 'shared'], takeaway='Retain exact source wording.', caveats=['Keep this condition.']),
        PresentationTopic(id='second', title='Second question', question='Second?', rationale='Second source priority.',
            series_ids=['shared', 'b'])])
    options = [dict(option_id='scope0', retained_topic_ids=['first'], omitted_topic_ids=['second'],
                    measured_analysis_slides=2)]
    choice = PhysicalBudgetScopeChoice(mode='whole_topics', option_id='scope0', reason='First question has higher source-supported priority.',
        decisions=[dict(series_id=sid, include=keep, reason='Explicit model priority for ' + sid)
                   for sid, keep in [('a', True), ('shared', True), ('b', False)]])
    return original, options, choice


def test_budget_reviews_only_native_source_notes_on_their_own_topic_pages():
    from types import SimpleNamespace as Row
    from adaptive_document_agent.agent.presentation_budget_geometry import visible_topic_notes
    deck = Row(slides=[Row(shapes=[Row(name='source_context:definitions_and_limits',
        has_text_frame=True, text='A conditional source definition.'), Row(name='unrelated')]),
        Row(shapes=[])])
    assert visible_topic_notes(deck, [dict(topic_id='a', physical_slide_numbers=[1]),
        dict(topic_id='b', physical_slide_numbers=[2])]) == [
        dict(topic_id='a', slide=1, text='A conditional source definition.')]


def test_rejected_whole_topic_copy_can_be_reworded_on_measured_retry():
    from types import SimpleNamespace
    from adaptive_document_agent.agent.presentation_budget_scope import last_rejected_whole_scope
    original, _, choice = case()
    prior = dict(scope_choice=choice.model_dump(), independent_review=dict(accepted=False, reason='Missing caveat'))
    counts = dict(analysis=11)
    audit = dict(original_selection=original.model_dump(mode='json'), original_counts=counts, attempts=[prior])
    saved = SimpleNamespace(validation_warnings=[
        SimpleNamespace(code='presentation_physical_budget_failed', message=json.dumps(audit)),
        SimpleNamespace(code='presentation_physical_budget_failed', message='Last refusal')])
    assert last_rejected_whole_scope(saved, original, counts) == prior
    assert last_rejected_whole_scope(saved, original, dict(analysis=8)) is None
    from adaptive_document_agent.agent.presentation_budget_scope import TopicQualification
    choice.additional_qualifications = [TopicQualification(topic_id='first', caveat='The later period is unaudited.')]
    revised = bind_scope_choice(choice, case()[1], original)
    assert revised.topics[0].caveats == [*original.topics[0].caveats, 'The later period is unaudited.']
    assert revised.topics[0].series_ids == original.topics[0].series_ids
    choice.additional_qualifications[0].topic_id = 'second'
    with pytest.raises(ValueError, match='retained topic'):
        bind_scope_choice(choice, case()[1], original)


def test_binding_keeps_exact_selected_topics_and_shared_series_without_writing_copy():
    original, options, choice = case()
    before = deepcopy(original)
    draft = bind_scope_choice(choice, options, original)
    assert draft.topics[0].model_dump() == original.topics[0].model_dump()
    assert len(draft.topics) == 1 and draft.decisions == choice.decisions
    draft.topics[0].title = 'Changed draft'
    assert original == before


@pytest.mark.parametrize('defect', ['unknown_option', 'wrong_include', 'missing', 'duplicate', 'unknown_series'])
def test_invalid_scope_or_series_ledger_never_selects_a_substitute(defect):
    original, options, choice = case()
    if defect == 'unknown_option':
        choice.option_id = 'scope999'
    elif defect == 'wrong_include':
        choice.decisions[1].include = False
    elif defect == 'missing':
        choice.decisions.pop()
    elif defect == 'duplicate':
        choice.decisions.append(choice.decisions[0])
    else:
        choice.decisions[0].series_id = 'unknown'
    with pytest.raises(ValueError, match='Whole-topic'):
        bind_scope_choice(choice, options, original)


def test_partial_series_route_is_explicit_and_cannot_claim_a_completed_whole_scope():
    original, options, _ = case()
    choice = PhysicalBudgetScopeChoice(mode='refine_series', reason='Needed qualifiers span full topics; refine their own series.')
    assert bind_scope_choice(choice, options, original) is None
    choice.option_id = 'scope0'
    with pytest.raises(ValueError, match='Partial-series'):
        bind_scope_choice(choice, options, original)


def test_scope_request_preserves_full_source_messages_and_uses_one_existing_proposal_slot():
    original, options, choice = case()
    context = dict(required_physical_change=dict(whole_topic_reference_options=dict(status='available', options=options)))
    messages = [dict(role='system', content='Original rules'), dict(role='user', content='Complete original evidence')]
    before = deepcopy(messages)

    class Gateway:
        calls = 0
        def generate_structured(self, sent, schema, **kwargs):
            self.calls += 1
            assert sent[:2] == messages and schema is PhysicalBudgetScopeChoice
            assert json.loads(sent[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])['scope_options'] == options
            return choice

    gateway, record = Gateway(), {}
    assert choose_whole_topic_scope(gateway, messages, context, original, record).topics[0].id == 'first'
    assert gateway.calls == 1 and messages == before
    assert record['scope_choice'] == choice.model_dump(mode='json')


def test_unavailable_menu_skips_the_scope_request_and_privacy_never_falls_back():
    original, options, _ = case()
    class Gateway:
        def generate_structured(self, *args, **kwargs):
            raise PrivacyViolationError('Local Only denies cloud content')
    context = dict(required_physical_change=dict(whole_topic_reference_options=dict(status='unavailable', options=[])))
    assert choose_whole_topic_scope(Gateway(), [], context, original, {}) is None
    context['required_physical_change']['whole_topic_reference_options'] = dict(status='available', options=options)
    with pytest.raises(PrivacyViolationError):
        choose_whole_topic_scope(Gateway(), [], context, original, {})
