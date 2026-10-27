"""A failed semantic check must not remove available original audit evidence."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _fingerprint,
    require_report_audit_scope, review_report_audit_scope, reviewed_audit_bindings,
)
from adaptive_document_agent.agent.report_audit_context_budget import require_audit_context_budget
from tests.test_report_audit_scope_v174 import fixture, covered_source


@pytest.mark.parametrize('status', ['unchecked', 'incomplete', 'failed', 'checked_not_found', 'checked_found'])
def test_nominated_source_pages_are_complete_regardless_of_prior_semantic_status(status):
    result, _ = fixture()
    check = result.profile.source_coverage.checks[0]
    check.status = status
    if status == 'failed': check.finding = 'Earlier source-summary output did not validate.'
    before = deepcopy(result)
    context = _context(result)
    assert context['source_pages'] == [dict(page=p.page_number, text=p.text) for p in result.document.pages]
    assert context['source_checks'][0]['status'] == status
    assert result == before
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)


@pytest.mark.parametrize('accepted', [False, True])
def test_missing_entity_correction_can_use_failed_checks_pages_but_still_needs_review(accepted):
    result, valid = fixture()
    result.profile.source_coverage.checks[0].status = 'failed'
    result.profile.source_coverage.checks[0].finding = 'Earlier bounded semantic check failed.'
    before = deepcopy((result.document, result.observations, result.profile.source_coverage))
    invalid = deepcopy(valid)
    invalid['scope_evidence'] = [dict(page=5, text='RMB’000. Revenue 120,462.')]

    class Gateway:
        drafts = 0
        reviews = 0

        def generate_structured(self, messages, schema, **kwargs):
            if schema is AuditScopeDraft:
                self.drafts += 1
                payload = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                assert payload['source_checks'][0]['status'] == 'failed'
                assert next(p['text'] for p in payload['source_pages'] if p['page'] == 4) == result.document.pages[3].text
                return schema(bindings=[invalid if self.drafts == 1 else valid],
                    unresolved_observation_ids=['ratio'], unresolved_reason='Ratio has no exact covered amount.')
            assert schema is AuditScopeReview
            self.reviews += 1
            return schema(verdicts=[dict(observation_id='amount', accepted=accepted,
                covered_source=covered_source(valid) if accepted else None,
                reason='Exact source chain is supported.' if accepted else 'The scope does not support this binding.')],
                unresolved_accepted=True, unresolved_reason='Ratio stays unknown.')

    gateway = Gateway()
    if accepted:
        review_report_audit_scope(gateway, result)
        require_report_audit_scope(result)
        assert gateway.drafts == 2 and gateway.reviews == 1
    else:
        with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
            review_report_audit_scope(gateway, result)
        assert not reviewed_audit_bindings(result)
        assert gateway.drafts == 3 and gateway.reviews == 2
    assert (result.document, result.observations, result.profile.source_coverage) == before


def test_newly_available_failed_check_text_invalidates_old_context_and_never_truncates():
    result, _ = fixture()
    result.profile.source_coverage.checks[0].status = 'failed'
    before = _context(result)
    result.document.pages[3].text += '\nNew source qualification.'
    assert _fingerprint(before) != _fingerprint(_context(result))
    result.document.pages[3].text = 'Full source evidence. ' * 10_000
    context = _context(result)
    assert context['source_pages'][3]['text'] == result.document.pages[3].text
    with pytest.raises(ValueError, match='no page was truncated'):
        require_audit_context_budget(context)
