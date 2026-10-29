import json

import pytest

from adaptive_document_agent.agent.topic_evidence_review import (
    TopicEvidenceReview, evidence_payload, review_topic_evidence, require_topic_evidence_review,
)
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.models import PresentationTopic, PresentationTopicSelection
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName, PrivacyMode
from tests.test_topic_coverage_review import _fixture


def decision(identifier, supported=True):
    return dict(topic_id=identifier, supported=supported,
                reason='The selected literal measure supports the question.' if supported else
                'The question names activity, but the selected source row measures waste.')


def setup():
    result, _, lookup, annual, _, adverse = _fixture()
    topic = PresentationTopic(id='activity', title='Output', question='How did output move?',
        rationale='The source supports a comparison of output.', series_ids=[adverse])
    return result, lookup, annual, adverse, PresentationTopicSelection(topics=[topic])


def gateway(responses):
    client = MockLLMClient(responses)
    return LLMGateway(client, LLMSettings(provider=ProviderName.OLLAMA, model='local',
        base_url='http://127.0.0.1:11434', privacy_mode=PrivacyMode.LOCAL_ONLY)), client


def test_wrong_valid_id_is_rebound_by_model_then_reviewed_against_full_new_rows():
    result, lookup, annual, adverse, selection = setup()
    raw = [o.model_dump() for o in result.observations]
    corrected = selection.model_copy(deep=True)
    corrected.topics[0].series_ids = [annual]
    g, client = gateway([{'decisions': [decision('activity', False)]}, corrected.model_dump(),
                         {'decisions': [decision('activity')]}])
    selected = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert selected == corrected and selection.topics[0].series_ids == [adverse]
    assert len(client.calls) == 3
    assert annual in client.calls[2][-1]['content'] and '"metric_original":"Output"' in client.calls[2][-1]['content']
    assert [o.model_dump() for o in result.observations] == raw
    result.pipeline_version = 'current'
    require_topic_evidence_review(selected, lookup, result)
    with pytest.raises(ValueError, match='semantic review'):
        require_topic_evidence_review(selection, lookup, result)
    assert g.settings.privacy_mode == PrivacyMode.LOCAL_ONLY


def test_rejected_correction_never_inherits_supported_sibling_or_self_certifies():
    result, lookup, annual, _, selection = setup()
    sibling = selection.topics[0].model_copy(update={'id': 'good', 'series_ids': [annual]})
    selection.topics.append(sibling)
    repeated = PresentationTopicSelection(topics=[selection.topics[0]])
    g, client = gateway([{'decisions': [decision('activity', False), decision('good')]},
                        repeated.model_dump(), {'decisions': [decision('activity', False)]}])
    reviewed = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert reviewed.topics == [sibling] and len(client.calls) == 3
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['omitted_topic_ids'] == ['activity'] and len(audit['accepted_bindings']) == 1
    assert audit['attempts'][1]['response']['topics'][0] == selection.topics[0].model_dump(mode='json')


@pytest.mark.parametrize('response', [[], [decision('wrong')], [decision('activity'), decision('activity')]])
def test_incomplete_or_unbound_reviews_fail_closed(response):
    result, lookup, _, _, selection = setup()
    g, client = gateway([{'decisions': response}])
    with pytest.raises(ValueError, match='exactly once'):
        review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert len(client.calls) == 1
    assert not json.loads(result.validation_warnings[-1].message)['accepted_bindings']


def test_changed_fact_or_question_invalidates_review_and_legacy_cannot_recover_without_review():
    result, lookup, annual, _, selection = setup()
    selection.topics[0].series_ids = [annual]
    result.pipeline_version = 'legacy'
    with pytest.raises(ValueError, match='semantic review'):
        require_topic_evidence_review(selection, lookup, result)
    g, _ = gateway([{'decisions': [decision('activity')]}])
    reviewed = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    require_topic_evidence_review(reviewed, lookup, result)
    lookup[annual][0].metric_original = 'Different measure'
    with pytest.raises(ValueError, match='semantic review'):
        require_topic_evidence_review(reviewed, lookup, result)


def test_oversize_does_not_sample_facts_or_call_model(monkeypatch):
    from adaptive_document_agent.agent import topic_evidence_review as module
    result, lookup, _, _, selection = setup()
    monkeypatch.setattr(module, 'MAX_CONTEXT', 10)
    g, client = gateway([])
    with pytest.raises(ValueError, match='no facts sampled'):
        review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert not client.calls


def test_selector_independently_reviews_valid_known_ids(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review
    result, lookup, annual, _, selection = setup()
    monkeypatch.setattr(topic_coverage_review, 'review_topic_coverage', lambda s, *a, **kw: s)
    corrected = selection.model_copy(deep=True)
    corrected.topics[0].series_ids = [annual]
    g, client = gateway([selection.model_dump(), {'decisions': [decision('activity', False)]},
                        corrected.model_dump(), {'decisions': [decision('activity')]}])
    actual = PresentationTopicSelector(g).select(result)
    assert actual == corrected and len(client.calls) == 4
    assert {'topic_initial_selection', 'topic_validation_repair', 'topic_source_review',
            'topic_coverage_review', 'topic_caveat_review', 'topic_final_source_review'} <= result.stage_details_ms.keys()


def test_identity_columns_remain_literal_when_repeated_cells_are_factored():
    from adaptive_document_agent.agent.context_dictionary import factor_series_cells
    label = 'Exact arbitrary operational metric ' * 8
    payload = dict(series_columns=['id', 'metric', 'unit'], all_extracted_series=[
        [f'id-{i}', label, 'long repeated unit ' * 20] for i in range(30)])
    actual = factor_series_cells(payload)
    assert all(row[1] == label for row in actual['all_extracted_series'])
    assert 'metric' not in actual['series_value_dictionaries']


def test_real_version_compiler_requires_review_and_keeps_it_when_source_scope_is_unchanged():
    from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan, reconcile_topic_source_scope
    from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
    result, lookup, annual, _, selection = setup()
    selection.topics[0].series_ids = [annual]
    result.pipeline_version = PIPELINE_VERSION
    result.presentation_topics = selection
    result.charts = []  # The generic fixture's revenue chart is outside this operational topic.
    with pytest.raises(ValueError, match='semantic review'):
        compile_topic_plan(result)
    lookup = reconcile_topic_source_scope(result)
    g, _ = gateway([{'decisions': [decision('activity')]}])
    result.presentation_topics = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    plan = compile_topic_plan(result)
    assert [t.id for t in plan.themes] == ['activity']
