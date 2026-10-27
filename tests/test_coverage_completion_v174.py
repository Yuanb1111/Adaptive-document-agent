"""Schema recovery must finish the full ledger before completion or delivery."""
import json
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.coverage_delta_review import TopicCoverageDelta
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_coverage_review import TopicCoverageReview, review_topic_coverage
from adaptive_document_agent.models import PresentationTopicSelection, ValidationIssue
from adaptive_document_agent.services.pipeline_completion import (
    is_complete, is_reporting_ready, require_topic_coverage, topic_coverage_complete,
)
from tests.test_bounded_topic_coverage import context_fixture
from tests.test_budget_output_v145 import gateway, response
from tests.test_coverage_delta_v147 import decisions, force_delta
from tests.test_topic_coverage_review import _topic


def prepared(monkeypatch):
    force_delta(monkeypatch)
    result, lookup, annual, interim, adverse, raw = context_fixture()
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    result.presentation_topics = selected
    ids = [sid for sid in lookup if sid != annual]
    delta = decisions(TopicCoverageDelta, ids, [interim, adverse])
    valid = TopicCoverageReview(topics=[_topic(annual), _topic(interim, 'recent'), _topic(adverse, 'constraint')],
                               coverage_decisions=delta.model_dump()['coverage_decisions'])
    oversized = valid.model_dump(mode='json')
    oversized['topics'] = [dict(valid.topics[i % 3].model_dump(), id=f'topic{i}') for i in range(15)]
    oversized['omissions'] = [dict(series_id=interim, reason='Provisional display summary') for _ in range(19)]
    return result, lookup, selected, raw, delta, valid, oversized


@pytest.mark.parametrize('wrapped', [False, True])
def test_complete_oversized_merge_gets_one_source_aware_correction(monkeypatch, wrapped):
    result, lookup, selected, raw, delta, valid, oversized = prepared(monkeypatch)
    invalid = json.dumps(oversized)
    if wrapped:
        invalid = '```json\n' + invalid + '\n```'
    llm, client = gateway([response(delta), response(invalid), response(valid)])
    snapshot = deepcopy(result.observations)
    result.presentation_topics = review_topic_coverage(selected, result, lookup, set(), raw, llm,
                                                       PresentationTopicSelector._validate)
    assert len(client.requests) == 3
    assert client.requests[1][0] == client.requests[2][0][:len(client.requests[1][0])]
    assert result.presentation_topics.topics == valid.topics
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['merge']['status'] == 'complete' and audit['calls_used'] == 3
    assert len(audit['review']['coverage_decisions']) == 2
    assert 'too_long' in audit['merge']['attempts'][0]['validation_error']
    assert topic_coverage_complete(result) and is_complete(result)
    assert result.observations == snapshot


def test_repeated_oversized_merge_stays_retryable_and_blocks_completed_cached_export(monkeypatch):
    result, lookup, selected, raw, delta, _, oversized = prepared(monkeypatch)
    llm, client = gateway([response(delta), response(json.dumps(oversized)), response(json.dumps(oversized))])
    result.presentation_topics = review_topic_coverage(selected, result, lookup, set(), raw, llm,
                                                       PresentationTopicSelector._validate)
    assert len(client.requests) == 3 and result.presentation_topics == selected
    assert is_reporting_ready(result) and not is_complete(result)
    assert not topic_coverage_complete(result)
    with pytest.raises(ValueError, match='source coverage review'):
        require_topic_coverage(result)
    import adaptive_document_agent.services.company_summary as summary
    import adaptive_document_agent.services.pptx_export as export
    monkeypatch.setattr(summary, 'require_verified_introduction', lambda result: None)
    monkeypatch.setattr(export, '_compose_presentation', lambda *a, **kw: pytest.fail('Unreviewed deck composed'))
    with pytest.raises(ValueError, match='source coverage review'):
        export.build_presentation(result)


def test_later_success_clears_failure_and_source_changes_expire_approval(monkeypatch):
    result, lookup, selected, raw, delta, valid, _ = prepared(monkeypatch)
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_coverage_unresolved',
        severity='warning', stage='presentation', message='Merge failed', related_ids=[]))
    assert not topic_coverage_complete(result)  # Empty warning IDs cannot approve a failed merge.
    llm, _ = gateway([response(delta), response(valid)])
    result.presentation_topics = review_topic_coverage(selected, result, lookup, set(), raw, llm,
                                                       PresentationTopicSelector._validate)
    assert is_complete(result)
    result.observations[0].raw_value += ' changed'
    assert not is_complete(result)


@pytest.mark.parametrize('failure', ['length', 'malformed', 'transport'])
def test_failed_physical_request_is_not_semantically_rewritten(monkeypatch, failure):
    from adaptive_document_agent.services.llm.exceptions import LLMTransportError
    result, lookup, selected, raw, delta, valid, _ = prepared(monkeypatch)
    failed = (LLMTransportError('Unavailable') if failure == 'transport' else
              response('{"topics":', finish='length' if failure == 'length' else 'stop'))
    # Proven length failures have one identical-context capacity retry. After
    # that bound, neither partial JSON nor a semantic rewrite may be accepted.
    failures = [failed, failed] if failure == 'length' else [failed]
    llm, client = gateway([response(delta), *failures, response(valid)])
    result.presentation_topics = review_topic_coverage(selected, result, lookup, set(), raw, llm,
                                                       PresentationTopicSelector._validate)
    assert len(client.requests) == 1 + len(failures) and len(client.outputs) == 1
    if failure == 'length':
        assert client.requests[1][0] == client.requests[2][0]
        assert client.requests[2][1]['max_tokens'] > client.requests[1][1]['max_tokens']
    assert not is_complete(result)
