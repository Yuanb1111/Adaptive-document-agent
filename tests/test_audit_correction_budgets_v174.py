"""A source-row correction does not consume the first semantic correction."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, require_report_audit_scope,
    review_report_audit_scope, reviewed_audit_bindings,
)
from tests.test_report_audit_scope_v174 import fixture


def detail_case():
    result, binding = fixture()
    amount = result.observations[0]
    amount.metric_original = 'Outsourced production costs'
    amount.raw_value = '417'
    amount.value = 417_000
    amount.evidence[0].row_label = amount.metric_original
    amount.evidence[0].text = amount.raw_value
    target = ('Example Group consolidated results for 6M2025. '
              'Outsourced production costs 417. Amounts in RMB thousands.')
    result.document.pages[0].text = target
    result.observations = [amount]
    result.presentation_plan.themes[0].observation_ids = ['amount']
    result.presentation_plan.slides[0].observation_ids = ['amount']
    # The appendix still shows only total Revenue, not this management detail.
    binding.update(status='unaudited', source_metric=amount.metric_original,
                   source_raw_value='417', source_unit='RMB thousands',
                   target_quote=dict(page=1, text=target), value_quote=dict(page=1, text=target),
                   header_quote=dict(page=1, text='consolidated results for 6M2025.'),
                   unit_quote=dict(page=1, text='Amounts in RMB thousands.'))
    invalid = deepcopy(binding)
    invalid['header_quote']['text'] = 'Fabricated header for 6M2025.'
    invalid['value_quote']['text'] = '417. Amounts in RMB thousands.'
    return result, binding, invalid


class CorrectionGateway:
    def __init__(self, binding, invalid, outcomes):
        self.binding, self.invalid, self.outcomes = binding, invalid, outcomes
        self.calls = []
        self.drafts = 0
        self.feedback_kinds = []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((schema, kwargs))
        if schema is AuditScopeDraft:
            self.drafts += 1
            assert self.drafts <= 3
            if self.drafts > 1:
                feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                self.feedback_kinds.append(feedback['corrective_kind'])
                assert 'never merely flip' in messages[-1]['content'].casefold()
                assert 'Failure to establish unaudited status does not establish audited status.' in messages[-1]['content']
                assert 'same entity or year, a total amount' in messages[-1]['content']
                if feedback['corrective_kind'] == 'independent_review':
                    assert feedback['independent_review']['verdicts'][0]['accepted'] is False
            outcome = self.outcomes[self.drafts - 1]
            if outcome == 'unknown':
                return schema(bindings=[], unresolved_observation_ids=['amount'],
                    unresolved_reason='No supplied audited financial-statement row covers this exact detail amount.')
            return schema(bindings=[self.invalid if outcome == 'binding' else self.binding])
        assert schema is AuditScopeReview
        if self.outcomes[self.drafts - 1] == 'unknown':
            return schema(verdicts=[], unresolved_accepted=True,
                unresolved_reason='The supplied audited grid has the total, but not this precise detail row.')
        return schema(verdicts=[dict(observation_id='amount', accepted=False,
            reason='The unaudited mark applies to the comparative; the year belongs to audited Relevant Periods.')],
            unresolved_accepted=True, unresolved_reason='No unknown IDs were proposed.')


@pytest.mark.parametrize('outcomes,kinds', [
    (['binding', 'semantic', 'unknown'], ['binding_validation', 'independent_review']),
    (['semantic', 'binding', 'unknown'], ['independent_review', 'binding_validation']),
])
def test_each_correction_kind_has_one_opportunity_then_exact_unknown_is_independently_reviewed(outcomes, kinds):
    result, binding, invalid = detail_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    gateway = CorrectionGateway(binding, invalid, outcomes)
    review_report_audit_scope(gateway, result)
    require_report_audit_scope(result)
    assert gateway.drafts == 3 and gateway.feedback_kinds == kinds
    assert len(gateway.calls) == 5  # Three drafts, rejection, and separate final unknown approval.
    assert not reviewed_audit_bindings(result)  # Reviewer rejection never becomes opposite assurance.
    record = json.loads(result.validation_warnings[-1].message)
    batch = record['batches'][0]
    assert batch['correction_limits'] == dict(binding_validation=1, independent_review=1,
                                             review_output=1, max_drafts=3)
    assert batch['corrections_used'] == dict(binding_validation=1, independent_review=1, review_output=0)
    assert batch['review']['unresolved_accepted'] is True
    assert (result.document, result.observations, result.analysis_results) == original


@pytest.mark.parametrize('outcomes,exhausted,drafts', [
    (['binding', 'binding'], 'binding_validation', 2),
    (['semantic', 'semantic'], 'independent_review', 2),
    (['binding', 'semantic', 'binding'], 'binding_validation', 3),
    (['semantic', 'binding', 'semantic'], 'independent_review', 3),
])
def test_repeated_failure_of_either_kind_cannot_borrow_more_attempts(outcomes, exhausted, drafts):
    result, binding, invalid = detail_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    gateway = CorrectionGateway(binding, invalid, outcomes)
    with pytest.raises(ValueError, match=exhausted + ' correction budget exhausted'):
        review_report_audit_scope(gateway, result)
    assert gateway.drafts == drafts
    assert result.validation_warnings[-1].code == 'report_audit_scope_unresolved'
    batch = json.loads(result.validation_warnings[-1].message)['batches'][0]
    assert len(batch['attempts']) == drafts
    assert batch['attempts'][-1]['correction_budget_exhausted'] is True
    assert batch['attempts'][-1]['corrective_kind'] == exhausted
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    assert not reviewed_audit_bindings(result)
    assert (result.document, result.observations, result.analysis_results) == original
