"""A bounded assurance batch cannot stand in for the full reviewed target ledger."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, review_report_audit_scope, require_report_audit_scope,
    reviewed_audit_bindings,
)
from adaptive_document_agent.agent.report_audit_batches import AUDIT_SCOPE_BATCH_SIZE
from tests.test_report_audit_scope_v174 import fixture, covered_source


def many_targets(count=38):
    result, binding = fixture()
    templates = result.observations
    result.observations = [templates[i % 2].model_copy(deep=True, update={
        'id': f"{'amount' if i % 2 == 0 else 'ratio'}-{i:02}", 'row_id': i // 2}) for i in range(count)]
    result.presentation_plan.themes[0].observation_ids = [o.id for o in result.observations]
    return result, binding


class BatchGateway:
    def __init__(self, binding, *, reject_group=None):
        from adaptive_document_agent.services.llm import LLMSettings, ProviderName
        from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
        self.settings = LLMSettings(provider=ProviderName.MOCK, model='offline-audit-fixture')
        self.client = SimpleNamespace(request_policy=lambda **kwargs:
            request_reasoning_policy(self.settings, **kwargs))
        self.binding = binding
        self.reject_group = reject_group
        self.groups = []
        self.calls = []
        self.bindings = []

    def generate_structured(self, messages, schema, **kwargs):
        context = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        ids = tuple(o['id'] for o in context['observations'])
        if ids not in self.groups:
            self.groups.append(ids)
        group = self.groups.index(ids)
        self.calls.append((schema, deepcopy(context), kwargs))
        if schema is AuditScopeDraft:
            self.bindings = [dict(deepcopy(self.binding), observation_id=o['id'])
                             for o in context['observations'] if o['unit'] == 'currency']
            return schema(bindings=self.bindings,
                unresolved_observation_ids=[o['id'] for o in context['observations'] if o['unit'] != 'currency'],
                unresolved_reason='No assurance of the exact percentages is present in the supplied sources.')
        assert schema is AuditScopeReview
        accepted = group != self.reject_group
        return schema(verdicts=[dict(observation_id=b['observation_id'], accepted=accepted,
            covered_source=covered_source(b) if accepted else None,
            reason='Exact amount is supported.' if accepted else 'Later batch does not establish scope.')
            for b in self.bindings], unresolved_accepted=accepted,
            unresolved_reason='Unknown ratios are justified.' if accepted else 'Later batch does not establish scope.')


def test_38_targets_receive_thirteen_complete_independent_batches_and_atomic_ledger():
    result, binding = many_targets()
    raw = deepcopy((result.document, result.observations, result.analysis_results))
    gateway = BatchGateway(binding)
    review_report_audit_scope(gateway, result)
    assert len(gateway.groups) == 13 and len(gateway.calls) == 26
    assert all(1 <= len(ids) <= AUDIT_SCOPE_BATCH_SIZE for ids in gateway.groups)
    assert {oid for ids in gateway.groups for oid in ids} == {o.id for o in result.observations}
    assert len([oid for ids in gateway.groups for oid in ids]) == 38
    # Complete source pages, not shortened quotations, reach every writer and
    # independent reviewer even though only three targets are assigned per call.
    first = gateway.calls[0][1]
    assert all(context['source_pages'] == first['source_pages'] and context['source_checks'] == first['source_checks']
               for _, context, _ in gateway.calls)
    assert all(kw['max_tokens'] <= 20000 and not kw['allow_repair'] and kw['stage'] == 'report'
               for _, _, kw in gateway.calls)
    assert (result.document, result.observations, result.analysis_results) == raw
    assert len([w for w in result.validation_warnings if w.code == 'report_audit_scope_review']) == 1
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['ledger']) == 38 and all(b['status'] == 'complete' for b in audit['batches'])
    assert len(reviewed_audit_bindings(result)) == 19
    require_report_audit_scope(result)


def test_later_batch_rejection_preserves_completed_batches_but_cannot_clear_final_gate():
    result, binding = many_targets(14)
    gateway = BatchGateway(binding, reject_group=1)
    with pytest.raises(ValueError, match='Later batch'):
        review_report_audit_scope(gateway, result)
    audit = json.loads(result.validation_warnings[-1].message)
    assert [b['status'] for b in audit['batches']] == ['complete', 'failed']
    assert not any(w.code == 'report_audit_scope_review' for w in result.validation_warnings)
    assert not reviewed_audit_bindings(result)
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    # Same source may resume already accepted batches, never the failed draft.
    completed = tuple(audit['batches'][0]['observation_ids'])
    recovered = BatchGateway(binding)
    review_report_audit_scope(recovered, result)
    assert completed not in recovered.groups
    assert len(recovered.calls) == 8
    require_report_audit_scope(result)
    recovered_audit = json.loads(result.validation_warnings[-1].message)
    assert recovered_audit['batches'][0]['reused_completed_batch']
    assert len(recovered_audit['ledger']) == 14


@pytest.mark.parametrize('mutation', ['missing_batch', 'duplicate_batch', 'unapproved_batch', 'wrong_ledger'])
def test_aggregate_metadata_cannot_mask_missing_or_unapproved_batch(mutation):
    result, binding = many_targets(14)
    review_report_audit_scope(BatchGateway(binding), result)
    issue = result.validation_warnings[-1]
    audit = json.loads(issue.message)
    if mutation == 'missing_batch':
        audit['batches'].pop()
    elif mutation == 'duplicate_batch':
        audit['batches'][-1] = audit['batches'][0]
    elif mutation == 'unapproved_batch':
        audit['batches'][-1]['review']['unresolved_accepted'] = False
    else:
        audit['ledger'][-1]['disposition'] = 'audited'
    issue.message = json.dumps(audit)
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)


def test_truncated_batch_has_only_two_fixed_capacity_attempts_and_no_independent_approval():
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    from tests.test_budget_output_v145 import gateway, response
    result, _ = many_targets(1)
    llm, client = gateway([response('', finish='length'), response('', finish='length')])
    with pytest.raises(LLMStructuredOutputError):
        review_report_audit_scope(llm, result)
    assert [kwargs['max_tokens'] for _, kwargs in client.requests] == [12000, 20000]
    assert client.requests[0][0] == client.requests[1][0]
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['batches']) == 1 and audit['batches'][0]['status'] == 'failed'
    assert 'review' not in audit['batches'][0] and 'ledger' not in audit
    with pytest.raises(ValueError):
        require_report_audit_scope(result)


class SplittingGateway(BatchGateway):
    def __init__(self, binding, *, rejected_id=None):
        super().__init__(binding)
        self.requests = []
        self.rejected_id = rejected_id

    def generate_structured(self, messages, schema, **kwargs):
        from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
        from tests.test_budget_output_v145 import response
        context = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        ids = tuple(o['id'] for o in context['observations'])
        self.requests.append((ids, schema, kwargs))
        if len(ids) > 1:
            raise LLMStructuredOutputError('Proven capacity limit', response=response('', finish='length'))
        value = super().generate_structured(messages, schema, **kwargs)
        if schema is AuditScopeReview and self.rejected_id in ids:
            for verdict in value.verdicts:
                verdict.accepted = False
                verdict.reason = 'Single target does not establish sufficient scope.'
            value.unresolved_accepted = False
            value.unresolved_reason = 'Single target does not establish sufficient scope.'
        return value


def test_proven_capacity_limits_split_to_independently_approved_singletons_with_finite_calls():
    result, binding = many_targets(6)
    gateway = SplittingGateway(binding)
    review_report_audit_scope(gateway, result)
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['capacity_splits']) == 4
    assert len(audit['batches']) == 6 and all(len(b['observation_ids']) == 1 for b in audit['batches'])
    assert len(gateway.requests) == 2 * (2 * 3 - 1) * 2
    assert len(audit['ledger']) == 6
    require_report_audit_scope(result)


def test_retry_reuses_proven_parent_truncations_and_accepted_leaves_but_not_rejected_leaf():
    result, binding = many_targets(6)
    failed = SplittingGateway(binding, rejected_id='amount-02')
    with pytest.raises(ValueError, match='Single target'):
        review_report_audit_scope(failed, result)
    partial = json.loads(result.validation_warnings[-1].message)
    known = {tuple(b['observation_ids']) for b in partial['capacity_splits']}
    completed = {tuple(b['observation_ids']) for b in partial['batches'] if b['status'] == 'complete'}
    assert known and completed
    with pytest.raises(ValueError):
        require_report_audit_scope(result)
    recovered = SplittingGateway(binding)
    review_report_audit_scope(recovered, result)
    assert not ({ids for ids, _, _ in recovered.requests} & (known | completed))
    assert ('amount-02',) in {ids for ids, _, _ in recovered.requests}
    require_report_audit_scope(result)


def _failed_first_checkpoint(result):
    """A persisted out-of-order run: the first group failed after others passed."""
    issue = result.validation_warnings[-1]
    audit = json.loads(issue.message)
    issue.code = 'report_audit_scope_unresolved'
    first = audit['batches'][0]
    first.update(status='failed', error='The first source group did not pass.')
    first.pop('draft')
    first.pop('review')
    for field in ('draft', 'review', 'ledger'):
        audit.pop(field)
    issue.message = json.dumps(audit)
    return audit


@pytest.mark.parametrize('workers', [1, 2])
def test_repeated_early_failure_keeps_completed_groups_that_did_not_start(monkeypatch, workers):
    from adaptive_document_agent.agent.report_audit_batches import resumable_batches
    result, binding = many_targets(14)
    raw = deepcopy((result.document, result.observations, result.analysis_results))
    review_report_audit_scope(BatchGateway(binding), result)
    previous = _failed_first_checkpoint(result)
    retained = resumable_batches(result, previous['context'])
    assert len(retained) == 4
    for record in retained.values():
        record['reused_completed_batch'] = True
    gateway = BatchGateway(binding, reject_group=0)
    gateway.discovery_workers = workers
    if workers == 2:
        # Deterministically model cancellation before the later queued groups
        # start. The actual thread cancellation/drain contract is tested below.
        from adaptive_document_agent.agent import report_audit_parallel
        def fail_before_queued_groups(gateway, groups, partitions, run, **kwargs):
            run(groups[0], partitions[0], gateway)
        monkeypatch.setattr(report_audit_parallel, 'review_groups_concurrently', fail_before_queued_groups)
    with pytest.raises(ValueError, match='Later batch'):
        review_report_audit_scope(gateway, result)
    latest = json.loads(result.validation_warnings[-1].message)
    assert [b['status'] for b in latest['batches']] == ['failed', *['complete'] * 4]
    assert resumable_batches(result, previous['context']) == retained
    assert len(gateway.groups) == 1
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    recovered = BatchGateway(binding)
    review_report_audit_scope(recovered, result)
    assert len(recovered.calls) == 2 and len(recovered.groups) == 1
    assert len(json.loads(result.validation_warnings[-1].message)['ledger']) == 14
    assert (result.document, result.observations, result.analysis_results) == raw
    require_report_audit_scope(result)


def test_repeated_early_failure_keeps_unvisited_proven_splits_and_accepted_leaves():
    from adaptive_document_agent.agent.report_audit_batches import resumable_batches
    result, binding = many_targets(6)
    review_report_audit_scope(SplittingGateway(binding), result)
    previous = _failed_first_checkpoint(result)
    retained = resumable_batches(result, previous['context'])
    for record in retained.values():
        record['reused_completed_batch'] = True
    split_ids = {tuple(record['observation_ids']) for record in previous['capacity_splits']}
    first_id = previous['batches'][0]['observation_ids'][0]
    with pytest.raises(ValueError, match='Single target'):
        review_report_audit_scope(SplittingGateway(binding, rejected_id=first_id), result)
    latest = json.loads(result.validation_warnings[-1].message)
    assert {tuple(record['observation_ids']) for record in latest['capacity_splits']} == split_ids
    assert resumable_batches(result, previous['context']) == retained
    assert [b['status'] for b in latest['batches']] == ['failed', *['complete'] * 5]
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    recovered = SplittingGateway(binding)
    review_report_audit_scope(recovered, result)
    assert len(recovered.requests) == 2
    assert {ids for ids, _, _ in recovered.requests} == {(first_id,)}
    require_report_audit_scope(result)


@pytest.mark.parametrize('parent_fails_first', [False, True])
def test_resume_preserves_old_accepted_leaves_even_without_capacity_diagnostics(parent_fails_first):
    from adaptive_document_agent.agent.report_audit_batches import resumable_batches
    result, binding = many_targets(6)
    review_report_audit_scope(SplittingGateway(binding), result)
    previous = _failed_first_checkpoint(result)
    # Capacity diagnostics may expire independently. Already accepted leaves
    # remain approved; only the incomplete leaf requires a new request.
    previous['capacity_splits'] = []
    result.validation_warnings[-1].message = json.dumps(previous)
    if parent_fails_first:
        retained = resumable_batches(result, previous['context'])
        for record in retained.values():
            record['reused_completed_batch'] = True
        with pytest.raises(ValueError, match='Later batch'):
            review_report_audit_scope(BatchGateway(binding, reject_group=0), result)
        assert resumable_batches(result, previous['context']) == retained
        with pytest.raises(ValueError, match='unfinished or stale'):
            require_report_audit_scope(result)
    gateway = BatchGateway(binding)
    review_report_audit_scope(gateway, result)
    latest = json.loads(result.validation_warnings[-1].message)
    assert len(latest['batches']) == 6 and len(latest['ledger']) == 6
    assert len({row['observation_id'] for row in latest['ledger']}) == 6
    assert len(gateway.calls) == 2
    require_report_audit_scope(result)


def test_semantic_rejection_does_not_trigger_capacity_subdivision():
    result, binding = many_targets(6)
    gateway = BatchGateway(binding, reject_group=0)
    with pytest.raises(ValueError):
        review_report_audit_scope(gateway, result)
    assert len(gateway.groups) == 1 and len(gateway.calls) == 4
    audit = json.loads(result.validation_warnings[-1].message)
    assert not audit['capacity_splits']


@pytest.mark.parametrize('target_count, should_pass', [(1, True), (2, False)])
def test_empty_unknown_set_is_not_a_rejection_of_an_accepted_binding(target_count, should_pass):
    result, binding = many_targets(target_count)
    class Gateway(BatchGateway):
        def generate_structured(self, messages, schema, **kwargs):
            value = super().generate_structured(messages, schema, **kwargs)
            if schema is AuditScopeReview:
                value.unresolved_accepted = False
                value.unresolved_reason = 'No unresolved observation IDs were supplied in this batch.'
            return value
    gateway = Gateway(binding)
    if should_pass:
        review_report_audit_scope(gateway, result)
        assert len(gateway.calls) == 2
        require_report_audit_scope(result)
    else:
        with pytest.raises(ValueError):
            review_report_audit_scope(gateway, result)
        with pytest.raises(ValueError):
            require_report_audit_scope(result)


def test_parallel_source_groups_are_bounded_and_merged_in_source_order():
    from threading import Barrier, Lock, get_ident
    from time import sleep
    result, binding = many_targets(14)
    caller = get_ident()
    progress_threads = []
    class Gateway:
        discovery_workers = 8  # The audit scheduler must still cap itself at two.
        def __init__(self):
            self.lock = Lock()
            self.barrier = Barrier(2)
            self.active = self.peak = self.calls = 0

        def generate_structured(self, messages, schema, **kwargs):
            assert kwargs['cancelled'] is not None
            context = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            with self.lock:
                self.calls += 1
                call = self.calls
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                if call <= 2:
                    self.barrier.wait(timeout=5)
                sleep(0.005)
                if schema is AuditScopeDraft:
                    return schema(bindings=[dict(deepcopy(binding), observation_id=o['id'])
                        for o in context['observations'] if o['unit'] == 'currency'],
                        unresolved_observation_ids=[o['id'] for o in context['observations'] if o['unit'] != 'currency'],
                        unresolved_reason='No source assurance for the exact ratios.')
                draft = json.loads(messages[2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                return schema(verdicts=[dict(observation_id=b['observation_id'], accepted=True,
                    covered_source=covered_source(b),
                    reason='Supported exact source measure.') for b in draft['bindings']],
                    unresolved_accepted=True, unresolved_reason='Ratios are not independently assured.')
            finally:
                with self.lock:
                    self.active -= 1
    gateway = Gateway()
    review_report_audit_scope(gateway, result, progress=lambda message: progress_threads.append(get_ident()))
    assert gateway.peak == 2 and gateway.calls == 10
    assert progress_threads and set(progress_threads) == {caller}
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['workers'] == 2
    from adaptive_document_agent.agent.report_audit_batches import batch_targets
    assert [b['observation_ids'] for b in audit['batches']] == batch_targets(audit['context'])
    require_report_audit_scope(result)


def test_parallel_failure_cancels_other_admissions_and_drains_workers():
    from threading import Barrier
    from adaptive_document_agent.agent.report_audit_parallel import review_groups_concurrently
    from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
    class Gateway:
        def __init__(self):
            self.calls = 0
        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError('Cancelled work must not reach the configured provider')
    gateway = Gateway()
    started = Barrier(2)
    partitions = [dict(batches=[], capacity_splits=[]) for _ in range(3)]
    def run(ids, partition, proxy, progress, cancelled):
        if ids[0] in {'first', 'second'}:
            started.wait(timeout=5)
        if ids == ['first']:
            raise PrivacyViolationError('Configured privacy boundary rejected the request')
        assert cancelled.wait(timeout=5)
        proxy.generate_structured([], AuditScopeDraft, stage='report')
    with pytest.raises(PrivacyViolationError, match='privacy boundary'):
        review_groups_concurrently(gateway, [['first'], ['second'], ['third']], partitions,
                                   run, workers=2)
    assert gateway.calls == 0
