import json

import pytest

from adaptive_document_agent.agent.catalog_topic_resume import retry_catalog_topics
from adaptive_document_agent.agent.retained_analysis_review import needs_catalog_retry
from adaptive_document_agent.agent.topic_evidence_review import review_payload
from adaptive_document_agent.models import ValidationIssue
from tests.test_catalog_timeout_resume import checkpoint, ReviewGateway
from tests.test_topic_source_pages_v209 import contextual_case


def test_review_keeps_period_audit_markers_separate_by_table():
    result, lookup, selection, _ = contextual_case()
    rows = lookup[selection.topics[0].series_ids[0]]
    rows[0].evidence[0].table_id = rows[1].evidence[0].table_id = 'same-table'
    rows[0].audited_status, rows[1].audited_status = 'unaudited', 'unknown'
    entries = review_payload(selection.topics, lookup, result)['selected_table_period_statuses']
    statuses = {e['period']: e['observed_statuses'] for e in entries if e['table_id'] == 'same-table'}
    assert statuses[rows[0].period] == ['unaudited']
    assert statuses[rows[1].period] == ['unknown']


@pytest.mark.parametrize('mutation', [None, 'source', 'newer_failure', 'series', 'missing_decision'])
def test_retry_restores_only_evidence_matched_post_coverage_drafts(mutation):
    saved = checkpoint()
    latest = saved.validation_warnings[-1]
    record = json.loads(latest.message)
    draft = record['review']['topics'][0].copy()
    sid = draft['series_ids'][0]
    record['candidate_series_ids'] = [sid]
    record['review']['coverage_decisions'] = ([] if mutation == 'missing_decision' else
        [dict(series_id=sid, decision='include', reason='Represented by selected source facts.')])
    latest.message = json.dumps(record)
    if mutation == 'series':
        draft['series_ids'] = ['changed']
    saved.validation_warnings.append(ValidationIssue(code='presentation_topic_evidence_review', stage='presentation',
        message=json.dumps(dict(original_topics=[draft], attempts=[]))))
    if mutation == 'newer_failure':
        saved.validation_warnings.append(ValidationIssue(code='presentation_topic_coverage_unresolved', stage='presentation', message='{}'))
    saved.presentation_topics = None
    saved.failed_stage, saved.failure_details = 'presentation_coverage', dict(component='TopicEvidenceReview')
    assert needs_catalog_retry(saved)
    current = saved.model_copy(deep=True)
    if mutation == 'source':
        current.observations[0].raw_value = 'changed'
    if mutation is None:
        with pytest.raises(RuntimeError, match='Independent topic review required'):
            retry_catalog_topics(saved, current, ReviewGateway(), None, None)
    else:
        assert retry_catalog_topics(saved, current, ReviewGateway(), None, None) is None


@pytest.mark.parametrize('rechecked', [False, True])
def test_legacy_wording_approval_expires_once_for_period_scope_review(rechecked):
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    from adaptive_document_agent.agent.topic_evidence_review import SOURCE_CONTEXT_CONTRACT, topic_binding
    saved = checkpoint()
    coverage = saved.validation_warnings[-1]
    record = json.loads(coverage.message)
    record.update(candidate_series_ids=[])
    record['review']['coverage_decisions'] = []
    coverage.message = json.dumps(record)
    _, lookup = series_directory(saved)
    topic = saved.presentation_topics.topics[0]
    binding = topic_binding(topic, lookup, saved)
    raw = topic.model_dump(mode='json')
    audit = dict(contract=SOURCE_CONTEXT_CONTRACT, original_topics=[raw], accepted_bindings=[binding],
        attempts=[dict(phase='coverage_wording_correction', response=dict(topics=[raw]))])
    saved.validation_warnings.append(ValidationIssue(code='presentation_topic_evidence_review',
        stage='presentation', message=json.dumps(audit)))
    if rechecked:
        audit.update(column_scope_guidance=True, attempts=[])
        saved.validation_warnings.append(ValidationIssue(code='presentation_topic_evidence_review',
            stage='presentation', message=json.dumps(audit)))
    saved.presentation_topics = None
    saved.failed_stage, saved.failure_details = 'presentation_coverage', dict(component='TopicEvidenceReview')
    current = saved.model_copy(deep=True)
    if rechecked:
        assert retry_catalog_topics(saved, current, ReviewGateway(), None, None).presentation_topics.topics == [topic]
    else:
        with pytest.raises(RuntimeError, match='Independent topic review required'):
            retry_catalog_topics(saved, current, ReviewGateway(), None, None)
