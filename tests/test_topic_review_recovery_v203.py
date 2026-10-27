"""Capacity failures never become semantic approval or erase verified siblings."""
import json
from concurrent.futures import CancelledError

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_evidence_review import TopicEvidenceReview, review_topic_evidence
from adaptive_document_agent.models import PresentationTopicSelection
from adaptive_document_agent.services.llm.exceptions import LLMTransportError, PrivacyViolationError
from adaptive_document_agent.services.pipeline_completion import is_complete, require_topic_coverage
from adaptive_document_agent.services.topic_review_status import topic_review_gaps
from tests.test_budget_output_v145 import gateway, response
from tests.test_topic_coverage_review import _fixture, _topic
from tests.test_topic_evidence_binding_v201 import decision


def selected(metric='Output', counterpoint='Waste'):
    result, _, lookup, annual, interim, adverse = _fixture(metric, counterpoint)
    topics = [_topic(annual, 'history'), _topic(interim, 'recent'), _topic(adverse, 'counterpoint')]
    return result, lookup, PresentationTopicSelection(topics=topics)


def verdict(*ids):
    return TopicEvidenceReview(decisions=[decision(i) for i in ids])


@pytest.mark.parametrize('metric,counterpoint', [
    ('Output', 'Waste'), ('Satisfaction', 'Turnover intention'), ('Reported result', 'Adjusted result'),
])
def test_real_gateway_retries_truncated_review_with_complete_unchanged_facts(metric, counterpoint):
    result, lookup, selection = selected(metric, counterpoint)
    original = [o.model_dump() for o in result.observations]
    expected = verdict('history', 'recent', 'counterpoint')
    g, client = gateway([response(expected, finish='length'), response(expected)])
    actual = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert actual == selection
    assert client.requests[0][0] == client.requests[1][0]
    assert [kw['max_tokens'] for _, kw in client.requests] == [16384, 24576]
    assert [o.model_dump() for o in result.observations] == original
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['accepted_bindings']) == 3 and not audit['unresolved_topics']
    assert audit['attempts'][0]['output_attempts'][0]['usage']['finish_reason'] == 'length'


def test_exhausted_batch_capacity_splits_only_complete_topics():
    result, lookup, selection = selected()
    cut = response('{"decisions":[', finish='length')
    g, client = gateway([cut, cut, response(verdict('history')), cut, cut,
                         response(verdict('recent')), response(verdict('counterpoint'))])
    assert review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate) == selection
    assert len(client.requests) == 7
    audits = json.loads(result.validation_warnings[-1].message)
    assert audits['capacity_splits'] == [['history', 'recent', 'counterpoint'], ['recent', 'counterpoint']]
    # Every successful child still owns every observation in its exact series.
    for index, topic in [(2, selection.topics[0]), (5, selection.topics[1]), (6, selection.topics[2])]:
        payload = client.requests[index][0][-1]['content']
        assert all(o.id in payload for sid in topic.series_ids for o in lookup[sid])


def test_unfinished_sibling_survives_as_visible_gap_and_blocks_completion():
    result, lookup, selection = selected()
    selection.topics.append(selection.topics[-1].model_copy(update={'id': 'unreviewed', 'title': 'Resource constraint'}))
    cut = response('{', finish='length')
    g, client = gateway([response(verdict('history', 'recent', 'counterpoint')), cut, cut])
    result.presentation_topics = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert len(result.presentation_topics.topics) == 3 and len(client.requests) == 3
    assert topic_review_gaps(result)[0]['title'] == 'Resource constraint'
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['omitted_topic_ids'] == []  # Missing verdict is not rejection.
    assert not is_complete(result)
    with pytest.raises(ValueError, match='Resource constraint'):
        require_topic_coverage(result)
    from adaptive_document_agent.ui.analysis_download import render_incomplete
    from tests.test_analysis_export_diagnostics import DownloadUI
    ui, shown = DownloadUI(), []
    ui.text = shown.append
    render_incomplete(ui, result, scope_key='unfinished')
    assert any('Resource constraint' in line for line in shown)
    assert 'analysis_data.json' in ui.downloads
    from adaptive_document_agent.agent.chart_planner import ChartPlanner
    from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.models import ValidationIssue
    result.charts = ChartPlanner().plan([], [], DocumentIndex(result.observations),
        requested_series=list(lookup.values()), only_requested=True)
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_coverage_unresolved',
        severity='warning', stage='presentation', message='Coverage still pending'))
    assert compile_topic_plan(result).editorial_status == 'degraded'


def test_fresh_complete_coverage_can_resolve_an_old_failed_question_but_stale_approval_cannot():
    from adaptive_document_agent.agent.coverage_review_binding import source_fingerprint
    from adaptive_document_agent.models import ValidationIssue
    result, lookup, selection = selected()
    gap = dict(topic_id='old-question', title='Prior framing', binding='failed-binding',
               series_ids=selection.topics[-1].series_ids, reason='Output truncated')
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_evidence_review',
        stage='presentation', severity='warning', message=json.dumps({'unresolved_topics': [gap]})))
    g, _ = gateway([response(verdict('history', 'recent', 'counterpoint'))])
    result.presentation_topics = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert topic_review_gaps(result)  # New wording alone is not a coverage review.
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_coverage_review',
        stage='presentation', severity='info', message=json.dumps(dict(
            source_fingerprint=source_fingerprint(lookup), review=selection.model_dump(mode='json')))))
    assert topic_review_gaps(result) == []
    lookup[next(iter(lookup))][0].raw_value = 'changed'
    assert topic_review_gaps(result)  # Evidence changes invalidate the old coverage.


def test_failed_coverage_merge_names_its_provisional_evidence_in_the_ui():
    from adaptive_document_agent.models import ValidationIssue
    from adaptive_document_agent.ui.analysis_download import render_incomplete
    from tests.test_analysis_export_diagnostics import DownloadUI
    result, lookup, selection = selected('Participation', 'Absence')
    result.presentation_topics = selection
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_coverage_unresolved',
        stage='presentation', severity='warning', related_ids=list(lookup),
        message=json.dumps({'unreviewed_series_ids': [], 'reason': 'Final merge truncated'})))
    ui, shown = DownloadUI(), []
    ui.text = shown.append
    render_incomplete(ui, result, scope_key='coverage')
    assert any('Participation' in line and '2024' in line for line in shown)
    assert any('Absence' in line for line in shown)
    assert 'analysis_data.json' in ui.downloads


@pytest.mark.parametrize('error', [PrivacyViolationError('private'), CancelledError('cancelled')])
def test_privacy_and_cancellation_escape_without_fallback(error):
    result, lookup, selection = selected()
    g, client = gateway([error])
    with pytest.raises(type(error)):
        review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert len(client.requests) == 1


def test_transport_failure_is_not_retried_as_output_capacity():
    result, lookup, selection = selected()
    g, client = gateway([LLMTransportError('offline')])
    with pytest.raises(ValueError, match='offline'):
        review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    assert len(client.requests) == 1
    assert len(topic_review_gaps(result)) == 3


def test_small_context_partitions_before_request_without_sampling(monkeypatch):
    from adaptive_document_agent.agent import topic_evidence_review as module
    result, lookup, selection = selected()
    lengths = [len(json.dumps(module.evidence_payload([t], lookup, result), separators=(',', ':')))
               for t in selection.topics]
    monkeypatch.setattr(module, 'MAX_CONTEXT', max(lengths) + 10)
    g, client = gateway([response(verdict(t.id)) for t in selection.topics])
    assert review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate) == selection
    assert len(client.requests) == 3


def test_coverage_capacity_retry_counts_every_physical_call():
    from threading import Event
    from adaptive_document_agent.agent.coverage_delta_review import _request, _Calls, TopicCoverageDelta
    value = TopicCoverageDelta(coverage_decisions=[dict(series_id='s', decision='include',
        reason='The latest outcome qualifies the historical view.')])
    g, client = gateway([response(value, finish='length'), response(value)])
    calls, audit = _Calls(2), {}
    assert _request(g, [], TopicCoverageDelta, audit, calls, Event(), tokens=8192,
                    characters=120000, validate=lambda x: x) == value
    assert calls.used == 2 and len(client.requests) == 2


def test_coverage_merge_at_absolute_ceiling_cannot_expand_again():
    from threading import Event
    from adaptive_document_agent.agent.coverage_delta_review import _request, _Calls, TopicCoverageDelta
    from adaptive_document_agent.agent.coverage_merge_capacity import MAX_MERGE_OUTPUT_TOKENS
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    g, client = gateway([response('{', finish='length')])
    calls = _Calls(2)
    with pytest.raises(LLMStructuredOutputError):
        _request(g, [], TopicCoverageDelta, {}, calls, Event(), tokens=MAX_MERGE_OUTPUT_TOKENS,
                 characters=120000, validate=lambda x: x)
    assert calls.used == len(client.requests) == 1
    assert client.requests[0][1]['max_tokens'] == MAX_MERGE_OUTPUT_TOKENS
