"""Retry retained proposals through fresh review, never through cached approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_batches import (
    AUDIT_REQUEST_STRATEGY, BATCHED_AUDIT_CONTRACT, batch_context,
)
from adaptive_document_agent.agent.report_audit_draft_resume import pending_audit_drafts
from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _fingerprint, _review_batch,
    review_report_audit_scope, reviewed_audit_bindings,
)
from adaptive_document_agent.models import ValidationIssue
from tests.test_audit_review_contract_v174 import ScriptedGateway
from tests.test_audit_scope_markers_v212 import marker_case


def checkpoint(*, malformed=True):
    result, draft, review = marker_case()
    context = _context(result)
    from adaptive_document_agent.agent.report_audit_source_discovery import discover_audit_sources
    context = discover_audit_sources(ScriptedGateway([]), result, context, {})
    ids = ['amount', 'ratio']
    entry = (dict(format_failure=dict(raw_response=json.dumps(draft)),
                  draft_output_attempts=[dict(status='invalid_format')]) if malformed else
             dict(draft=draft, draft_output_attempts=[dict(status='response_received')]))
    audit = dict(contract=BATCHED_AUDIT_CONTRACT, request_strategy=AUDIT_REQUEST_STRATEGY,
        context=context, fingerprint=_fingerprint(context), batches=[dict(
            observation_ids=ids, context_fingerprint=_fingerprint(batch_context(context, ids)),
            status='failed', attempts=[entry])])
    return result, context, audit, draft, review


def save(result, audit):
    result.validation_warnings.append(ValidationIssue(code='report_audit_scope_unresolved',
        stage='report', severity='warning', message=json.dumps(audit)))


@pytest.mark.parametrize('malformed', [True, False])
def test_production_retry_reviews_retained_proposal_without_regenerating_it(malformed):
    result, context, audit, draft, review = checkpoint(malformed=malformed)
    save(result, audit)
    original = deepcopy((result.document, result.observations, result.analysis_results, audit))
    gateway = ScriptedGateway([review])
    review_report_audit_scope(gateway, result)
    assert [call[1] for call in gateway.calls] == [AuditScopeReview]
    assert set(reviewed_audit_bindings(result)) == {'amount'}
    record = json.loads(result.validation_warnings[-1].message)['batches'][0]
    assert record['draft'] == draft and record['status'] == 'complete'
    assert record['retained_unreviewed_draft']['semantic_approval'] is False
    assert record['attempts'][0]['draft_origin'] == 'retained_unreviewed_draft'
    assert record['corrections_used'] == dict(draft_output=0, binding_validation=0,
        independent_review=0, review_output=0)
    assert (result.document, result.observations, result.analysis_results, audit) == original


@pytest.mark.parametrize('mutation', ['source', 'target', 'batch_fingerprint', 'contract',
    'strategy', 'rejected_review', 'malformed_review', 'truncated', 'invalid_draft',
    'superseded', 'duplicate', 'bad_json'])
def test_invalid_stale_rejected_or_superseded_proposals_are_not_resumed(mutation):
    result, context, audit, draft, review = checkpoint()
    entry = audit['batches'][0]['attempts'][-1]
    if mutation == 'source':
        context = deepcopy(context)
        context['source_pages'][0]['text'] += ' Changed source.'
    elif mutation == 'target':
        context = deepcopy(context)
        context['observations'][0]['raw_value'] = '999'
    elif mutation == 'batch_fingerprint':
        audit['batches'][0]['context_fingerprint'] = 'stale'
    elif mutation in {'contract', 'strategy'}:
        audit['contract' if mutation == 'contract' else 'request_strategy'] = 'old'
    elif mutation == 'rejected_review':
        review.verdicts[0].accepted = False
        entry['review'] = review.model_dump()
    elif mutation == 'malformed_review':
        entry['review_contract_corrections'] = [dict(raw_response='{}')]
    elif mutation == 'truncated':
        entry['draft_output_attempts'][-1]['status'] = 'truncated'
    elif mutation == 'invalid_draft':
        draft['bindings'][0]['source_raw_value'] = '999'
        entry['format_failure']['raw_response'] = json.dumps(draft)
    elif mutation == 'superseded':
        audit['batches'][0]['attempts'].append(dict(format_failure=dict(raw_response='{}')))
    elif mutation == 'duplicate':
        audit['batches'].append(deepcopy(audit['batches'][0]))
    else:
        entry['format_failure']['raw_response'] = 'not json'
    save(result, audit)
    assert pending_audit_drafts(result, context) == {}


def test_retained_draft_rejection_keeps_bounded_writer_correction_and_new_review():
    result, context, audit, _, review = checkpoint()
    save(result, audit)
    seed = pending_audit_drafts(result, context)[('amount', 'ratio')]
    review.verdicts[0].accepted = False
    review.verdicts[0].reason = 'The exact scope ownership is unsupported.'
    unknown = AuditScopeDraft(unresolved_observation_ids=['amount', 'ratio'],
        unresolved_reason='No exact covered counterpart establishes assurance for either target.')
    accepted = AuditScopeReview(verdicts=[], unresolved_accepted=True,
        unresolved_reason='Keeping these targets unknown is supported by the supplied source.')
    gateway = ScriptedGateway([review, unknown, accepted])
    record = dict(attempts=[], retained_unreviewed_draft=seed)
    _review_batch(gateway, batch_context(context, ['amount', 'ratio']), record)
    assert [c[1] for c in gateway.calls] == [AuditScopeReview, AuditScopeDraft, AuditScopeReview]
    assert record['draft']['bindings'] == []
    assert record['corrections_used']['independent_review'] == 1
    assert record['attempts'][0]['review']['verdicts'][0]['accepted'] is False
    assert record['status'] == 'complete'


def test_retained_proposal_does_not_relax_repeated_rejection_limit():
    result, context, audit, draft, review = checkpoint()
    save(result, audit)
    seed = pending_audit_drafts(result, context)[('amount', 'ratio')]
    review.verdicts[0].accepted = False
    gateway = ScriptedGateway([review, AuditScopeDraft.model_validate(draft), review])
    record = dict(attempts=[], retained_unreviewed_draft=seed)
    with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
        _review_batch(gateway, batch_context(context, ['amount', 'ratio']), record)
    assert len(gateway.calls) == 3
    assert 'status' not in record
    assert reviewed_audit_bindings(result) == {}


def test_false_page_coverage_acceptance_can_be_corrected_to_substantive_rejection():
    result, context, audit, _, review = checkpoint()
    save(result, audit)
    seed = pending_audit_drafts(result, context)[('amount', 'ratio')]
    invalid = review.model_copy(deep=True)
    invalid.verdicts[0].covered_source.page_coverage[0].page_label_quote.text = 'I-6'
    rejected = review.model_copy(deep=True)
    rejected.verdicts[0].accepted = False
    rejected.verdicts[0].covered_source = None
    rejected.verdicts[0].reason = 'The actual printed source page is not within the claimed range.'
    unknown = AuditScopeDraft(unresolved_observation_ids=['amount', 'ratio'],
        unresolved_reason='The complete exact counterpart coverage chain is not established.')
    accepted = AuditScopeReview(verdicts=[], unresolved_accepted=True,
        unresolved_reason='The source-specific unknown dispositions are supported.')
    gateway = ScriptedGateway([invalid, rejected, unknown, accepted])
    record = dict(attempts=[], retained_unreviewed_draft=seed)
    _review_batch(gateway, batch_context(context, ['amount', 'ratio']), record)
    assert [c[1] for c in gateway.calls] == [AuditScopeReview, AuditScopeReview,
                                          AuditScopeDraft, AuditScopeReview]
    correction = gateway.calls[1][0][-1]['content']
    assert 'accepted=false' in correction and 'covered_source=null' in correction
    assert record['corrections_used'] == dict(draft_output=0, binding_validation=0,
        independent_review=1, review_output=1)
    assert record['draft']['bindings'] == []
    assert record['status'] == 'complete'
