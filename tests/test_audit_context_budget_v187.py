"""Aggregate evidence may be large while every real audit request stays bounded."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_batches import batch_context, batch_targets
from adaptive_document_agent.agent.report_audit_context_budget import (
    MAX_AUDIT_CONTEXT_CHARS, audit_context_budget, require_audit_context_budget,
)
from adaptive_document_agent.agent.report_audit_scope import (
    _context, review_report_audit_scope, require_report_audit_scope, reviewed_audit_bindings,
)
from adaptive_document_agent.agent.report_audit_source_discovery import (
    AuditSourceDiscovery, _expanded_context, validate_audit_source_discovery,
)
from adaptive_document_agent.agent.report_audit_source_index import discovery_input
from tests.test_report_audit_batches_v174 import many_targets, BatchGateway


def large_aggregate():
    result, binding = many_targets(63)
    # Source text is preserved in every real request; only target IDs partition.
    result.document.pages[0].text += '\n' + 'Original page evidence. ' * 4000
    return result, binding


def test_63_targets_above_aggregate_limit_complete_all_21_independent_batches():
    result, binding = large_aggregate()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    context = _context(result)
    budget = require_audit_context_budget(context)
    assert budget['aggregate_characters'] > MAX_AUDIT_CONTEXT_CHARS
    assert budget['largest_batch_characters'] < MAX_AUDIT_CONTEXT_CHARS
    assert budget['batch_count'] == 21
    gateway = BatchGateway(binding)
    review_report_audit_scope(gateway, result)
    assert len(gateway.groups) == 21 and len(gateway.calls) == 42
    assert {oid for ids in gateway.groups for oid in ids} == {o.id for o in result.observations}
    assert all(request['source_pages'] == context['source_pages'] and
               request['source_checks'] == context['source_checks']
               for _, request, _ in gateway.calls)
    assert all(len(json.dumps(request, ensure_ascii=False)) <= MAX_AUDIT_CONTEXT_CHARS
               for _, request, _ in gateway.calls)
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['ledger']) == 63 and len(reviewed_audit_bindings(result)) == 32
    assert audit['context_budget'] == audit_context_budget(audit['context'])
    require_report_audit_scope(result)
    review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 42  # Unchanged accepted evidence does not buy another review.
    assert (result.document, result.observations, result.analysis_results) == original


def test_source_selection_budget_uses_largest_exact_request_not_aggregate_size():
    result, _ = large_aggregate()
    context = _context(result)
    payload, fingerprint = discovery_input(result, context)
    actual_max = max(len(json.dumps(batch_context(context, ids), ensure_ascii=False))
                     for ids in batch_targets(context))
    assert payload['remaining_source_character_budget'] == MAX_AUDIT_CONTEXT_CHARS - actual_max > 0
    assert len(payload['targets']) == 63
    assert payload['already_read_source_pages'] == context['source_pages']
    assert len(payload['page_index']) == result.document.page_count
    selection = AuditSourceDiscovery(rationale='All physical pages are present.')
    expanded = _expanded_context(result, context, payload, selection, fingerprint)
    assert expanded['observations'] == context['observations']
    assert expanded['source_pages'] == context['source_pages']


@pytest.mark.parametrize('oversize', ['source_page', 'single_target'])
def test_actual_oversize_batch_retains_diagnostics_and_never_calls_a_model(oversize):
    result, binding = many_targets(3)
    if oversize == 'source_page':
        result.document.pages[0].text += 'x' * MAX_AUDIT_CONTEXT_CHARS
    else:
        result.observations[0].evidence[0].text = 'x' * MAX_AUDIT_CONTEXT_CHARS
    gateway = BatchGateway(binding)
    with pytest.raises(ValueError, match='actual review batch.*no page was truncated'):
        review_report_audit_scope(gateway, result)
    assert not gateway.calls
    audit = json.loads(result.validation_warnings[-1].message)
    assert result.validation_warnings[-1].code == 'report_audit_scope_unresolved'
    assert audit['context_budget']['largest_batch_characters'] > MAX_AUDIT_CONTEXT_CHARS
    assert not audit['batches'] and 'ledger' not in audit
    assert not reviewed_audit_bindings(result)


def test_added_full_page_checks_expanded_batch_including_discovery_metadata():
    result, _ = large_aggregate()
    result.document.pages.append(result.document.pages[0].model_copy(deep=True,
        update=dict(page_number=8, text='Unread complete source page. ' * 2500)))
    result.document.page_count = 8
    context = _context(result)
    require_audit_context_budget(context)
    payload, fingerprint = discovery_input(result, context)
    section = next(s for s in payload['sections'] if s['start_page'] <= 8 <= s['end_page'])
    selection = AuditSourceDiscovery(ranges=[dict(section_id=section['id'], start_page=8,
        end_page=8, observation_ids=[result.observations[0].id], reason='Inspect the full counterpart page.')],
        rationale='A relevant unread page needs review.')
    before = deepcopy(result.document)
    with pytest.raises(ValueError, match='no page was truncated'):
        _expanded_context(result, context, payload, selection, fingerprint)
    assert result.document == before


def test_large_aggregate_rejection_still_blocks_acceptance_and_resumes_verified_batches():
    result, binding = large_aggregate()
    failed = BatchGateway(binding, reject_group=1)
    with pytest.raises(ValueError, match='Later batch'):
        review_report_audit_scope(failed, result)
    assert not reviewed_audit_bindings(result)
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    previous = json.loads(result.validation_warnings[-1].message)
    completed = tuple(previous['batches'][0]['observation_ids'])
    recovered = BatchGateway(binding)
    review_report_audit_scope(recovered, result)
    assert completed not in recovered.groups
    assert len(recovered.calls) == 40
    require_report_audit_scope(result)


def test_large_aggregate_source_change_expires_both_discovery_and_acceptance():
    result, binding = large_aggregate()
    review_report_audit_scope(BatchGateway(binding), result)
    audit = json.loads(result.validation_warnings[-1].message)
    result.document.pages[0].text += '\nChanged source qualification.'
    assert not reviewed_audit_bindings(result)
    with pytest.raises(ValueError, match='stale'):
        validate_audit_source_discovery(result, audit['context'], audit['source_discovery'])
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
