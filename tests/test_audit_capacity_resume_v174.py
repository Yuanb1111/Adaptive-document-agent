"""A new reasoning route expires capacity failures without erasing reviewed sources."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.report_audit_capacity import audit_capacity_identity
from adaptive_document_agent.agent.report_audit_batches import (
    AUDIT_REQUEST_STRATEGY, batch_context, resumable_batches, _known_capacity_splits,
)
from adaptive_document_agent.agent.report_audit_scope import (
    _fingerprint, review_report_audit_scope, require_report_audit_scope,
)
from adaptive_document_agent.services.llm import LLMSettings, ProviderName
from adaptive_document_agent.services.llm.config import PrivacyMode
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMTransportError
from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
from tests.test_report_audit_batches_v174 import BatchGateway, many_targets
from tests.test_budget_output_v145 import response


def configured_gateway(**overrides):
    settings = LLMSettings(provider=ProviderName.DEEPSEEK, model='deepseek-flash', **overrides)
    return SimpleNamespace(settings=settings, client=SimpleNamespace(request_policy=lambda **kwargs:
        request_reasoning_policy(settings, **kwargs)))


@pytest.mark.parametrize('field,value', [
    ('model', 'deepseek-v4-pro'), ('stage_models', {'report': 'deepseek-v4-pro'}),
    ('provider', ProviderName.OPENAI_COMPATIBLE), ('base_url', 'https://different.example/v1'),
    ('privacy_mode', PrivacyMode.LOCAL_ONLY), ('temperature', 0.2),
])
def test_capacity_identity_changes_with_exact_route_model_or_policy(field, value):
    gateway = configured_gateway()
    original = audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY)
    setattr(gateway.settings, field, value)
    assert audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY) != original


def test_simple_task_optout_does_not_change_complex_audit_capacity_policy():
    gateway = configured_gateway()
    original = audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY)
    gateway.settings.simple_task_reasoning = 'provider_default'
    assert audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY) == original


def test_capacity_identity_has_no_source_or_credentials_and_preserves_equivalent_routes(monkeypatch):
    from adaptive_document_agent.agent import report_audit_capacity
    from adaptive_document_agent.services.llm.credentials import DEFAULT_ENDPOINTS
    gateway = configured_gateway(api_key='secret-key-a')
    original = audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY)
    gateway.settings.api_key = 'secret-key-b'
    gateway.settings.base_url = DEFAULT_ENDPOINTS[ProviderName.DEEPSEEK]
    assert audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY) == original
    assert set(original) == {'contract', 'fingerprint'}
    assert 'secret' not in json.dumps(original) and 'deepseek.com' not in json.dumps(original)
    assert audit_capacity_identity(gateway, 'different-request-strategy') != original
    monkeypatch.setattr(report_audit_capacity, 'AUDIT_DRAFT_TOKEN_LIMITS', (12000, 20001))
    assert audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY) != original
    assert audit_capacity_identity(SimpleNamespace(), AUDIT_REQUEST_STRATEGY) is None


def test_review_contract_revision_expires_capacity_only_and_keeps_all_fifteen_approved_targets(monkeypatch):
    from adaptive_document_agent.agent import report_audit_capacity
    current_contract = report_audit_capacity.CAPACITY_CONTRACT
    with monkeypatch.context() as prior_policy:
        prior_policy.setattr(report_audit_capacity, 'CAPACITY_CONTRACT', 'audit-capacity-route-policy-v174')
        result, binding, prior = checkpoint()
    assert report_audit_capacity.CAPACITY_CONTRACT == current_contract
    # Keep the identical old reasoning policy, isolating just the reviewer-contract revision.
    gateway = BatchGateway(binding)
    gateway.settings.simple_task_reasoning = 'provider_default'
    current_capacity = audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY)
    with monkeypatch.context() as prior_policy:
        prior_policy.setattr(report_audit_capacity, 'CAPACITY_CONTRACT', 'audit-capacity-route-policy-v174')
        assert audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY) == prior['capacity_identity']
    assert prior['capacity_identity']['contract'] != current_capacity['contract']
    assert _known_capacity_splits(result, prior['context'], current_capacity) == {}
    ready = resumable_batches(result, prior['context'])
    assert sorted(len(ids) for ids in ready) == [1, 2, 3, 3, 3, 3]
    assert sum(map(len, ready)) == 15


class FifteenApprovedGateway(BatchGateway):
    """One historical length split approved 1+2; a later transport call failed."""
    def generate_structured(self, messages, schema, **kwargs):
        context = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        ids = tuple(row['id'] for row in context['observations'])
        if len(ids) == 3 and 'ratio-03' in ids:
            raise LLMStructuredOutputError('Proven old capacity failure', response=response('', finish='length'))
        if any(int(oid.rsplit('-', 1)[1]) >= 15 for oid in ids):
            raise LLMTransportError('Offline checkpoint after fifteen approved targets')
        return super().generate_structured(messages, schema, **kwargs)


def checkpoint(*, historical_reduced=False):
    result, binding = many_targets(38)
    gateway = FifteenApprovedGateway(binding)
    gateway.settings.simple_task_reasoning = 'provider_default'
    if historical_reduced:
        original_policy = gateway.client.request_policy
        def prior_policy(**kwargs):
            policy = original_policy(**kwargs)
            if kwargs['operation'] == 'AuditScopeDraft':
                return {**policy, 'intent': 'reduce', 'status': 'unsupported'}
            return policy
        gateway.client.request_policy = prior_policy
    with pytest.raises(LLMTransportError):
        review_report_audit_scope(gateway, result)
    audit = json.loads(result.validation_warnings[-1].message)
    completed = [b for b in audit['batches'] if b['status'] == 'complete']
    assert [len(b['observation_ids']) for b in completed] == [3, 1, 2, 3, 3, 3]
    assert sum(len(b['observation_ids']) for b in completed) == 15
    assert len(audit['capacity_splits']) == 1
    return result, binding, audit


@pytest.mark.parametrize('old_capacity', ['missing', 'changed'])
def test_all_fifteen_approvals_reuse_including_one_plus_two_after_capacity_policy_changes(old_capacity):
    result, binding, prior = checkpoint(historical_reduced=True)
    if old_capacity == 'missing':
        prior.pop('capacity_identity')
        result.validation_warnings[-1].message = json.dumps(prior)
    before = deepcopy((result.document, result.observations, result.analysis_results))
    ready = resumable_batches(result, prior['context'])
    accepted_ids = {oid for ids in ready for oid in ids}
    assert len(accepted_ids) == 15
    gateway = BatchGateway(binding)  # Current audit operations retain default reasoning.
    capacity = audit_capacity_identity(gateway, AUDIT_REQUEST_STRATEGY)
    assert _known_capacity_splits(result, prior['context'], capacity) == {}
    review_report_audit_scope(gateway, result)
    requested = {oid for ids in gateway.groups for oid in ids}
    assert len(requested) == 23 and not requested.intersection(accepted_ids)
    assert len(gateway.calls) == 16
    current = json.loads(result.validation_warnings[-1].message)
    assert current['capacity_identity'] == capacity
    assert current['fingerprint'] == prior['fingerprint']
    assert current['context'] == prior['context']
    assert current['request_strategy'] == prior['request_strategy'] == AUDIT_REQUEST_STRATEGY
    assert current['capacity_splits'] == []  # Resume partitions are not capacity evidence.
    assert sum(len(b['observation_ids']) for b in current['batches'] if b.get('reused_completed_batch')) == 15
    assert len(current['ledger']) == 38
    assert (result.document, result.observations, result.analysis_results) == before
    require_report_audit_scope(result)


def test_remaining_ids_are_resumed_without_reopening_a_partially_approved_parent():
    result, binding, prior = checkpoint(historical_reduced=True)
    # Only the first child of the historical 1+2 partition remains complete.
    child = next(b for b in prior['batches'] if len(b['observation_ids']) == 2)
    missing = set(child['observation_ids'])
    child.update(status='failed', error='The child review did not finish')
    child.pop('draft')
    child.pop('review')
    result.validation_warnings[-1].message = json.dumps(prior)
    gateway = BatchGateway(binding)
    review_report_audit_scope(gateway, result)
    assert tuple(child['observation_ids']) in gateway.groups
    assert not any('ratio-03' in ids for ids in gateway.groups)
    current = json.loads(result.validation_warnings[-1].message)
    assert current['capacity_splits'] == []
    assert len(current['ledger']) == 38
    require_report_audit_scope(result)


@pytest.mark.parametrize('mutation', ['stale', 'missing_proof', 'unapproved', 'ids_string',
                                     'duplicate', 'overlap', 'unknown_id', 'malformed_record'])
def test_invalid_or_overlapping_checkpoint_partitions_cannot_be_reused(mutation):
    result, _, audit = checkpoint()
    first = audit['batches'][0]
    if mutation == 'stale':
        first['context_fingerprint'] = 'stale'
    elif mutation == 'missing_proof':
        first['review']['verdicts'][0].pop('covered_source')
    elif mutation == 'unapproved':
        first['review']['verdicts'][0]['accepted'] = False
    elif mutation == 'ids_string':
        first['observation_ids'] = ''.join(first['observation_ids'])
    elif mutation == 'unknown_id':
        first['observation_ids'][0] = 'outside-targets'
    elif mutation == 'malformed_record':
        audit['batches'].append(None)
    elif mutation == 'duplicate':
        audit['batches'].append(deepcopy(first))
    else:
        overlap = deepcopy(first)
        ids = overlap['observation_ids'][:2]
        overlap['observation_ids'] = ids
        overlap['context_fingerprint'] = _fingerprint(batch_context(audit['context'], ids))
        overlap['draft']['bindings'] = [b for b in overlap['draft']['bindings'] if b['observation_id'] in ids]
        overlap['draft']['unresolved_observation_ids'] = [oid for oid in overlap['draft']['unresolved_observation_ids'] if oid in ids]
        overlap['review']['verdicts'] = [v for v in overlap['review']['verdicts'] if v['observation_id'] in ids]
        audit['batches'].append(overlap)
    result.validation_warnings[-1].message = json.dumps(audit)
    assert resumable_batches(result, audit['context']) == {}
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)


def test_an_unidentifiable_gateway_cannot_reuse_length_evidence_but_keeps_approvals():
    result, _, audit = checkpoint()
    assert _known_capacity_splits(result, audit['context'], None) == {}
    assert sum(len(ids) for ids in resumable_batches(result, audit['context'])) == 15
