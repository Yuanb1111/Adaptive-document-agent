"""Ineligible ratios need an explicit, independently reviewed unknown disposition."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_eligibility import audit_binding_ineligibility
from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, review_report_audit_scope,
    require_report_audit_scope, reviewed_audit_bindings,
)
from tests.test_report_audit_scope_v174 import fixture


def percentage_case():
    result, binding = fixture()
    ratio = result.observations[1]
    ratio.metric_original = 'Others: %of Total'
    ratio.raw_value = '3.1'
    ratio.value = 3.1
    ratio.period = '6M2024'
    ratio.evidence[0].row_label = 'Others'
    ratio.evidence[0].column_label = '%of Total'
    ratio.evidence[0].text = '3.1'
    target = 'Example Group cost breakdown for 6M2024. Others 2,090 3.1. Percent of Total (%).'
    result.document.pages[0].text = target
    result.observations = [ratio]
    result.presentation_plan.themes[0].observation_ids = ['ratio']
    result.presentation_plan.slides[0].observation_ids = ['ratio']
    binding.update(observation_id='ratio', status='unaudited', period='6M2024',
                   source_metric='Others', source_raw_value='3.1', source_unit='%',
                   source_unit_scale=1, source_currency=None,
                   target_quote=dict(page=1, text=target), value_quote=dict(page=1, text=target),
                   header_quote=dict(page=1, text='cost breakdown for 6M2024.'),
                   unit_quote=dict(page=1, text='Percent of Total (%).'),
                   reason='No source specifically assures the 3.1% ratio, so the binding is unaudited.')
    return result, binding


class PercentageGateway:
    def __init__(self, binding, *, ignore_eligibility=False, accept_unknown=True):
        self.binding = binding
        self.ignore_eligibility = ignore_eligibility
        self.accept_unknown = accept_unknown
        self.calls = []
        self.drafts = 0

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema)
        if schema is AuditScopeDraft:
            self.drafts += 1
            if self.drafts > 1:
                payload = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                contract = payload['target_contracts'][0]
                assert contract['allowed_dispositions'] == ['unresolved']
                assert contract['target_quote']['required_raw_value'] == '3.1'
                assert contract['retained_target']['unit'] == 'percent'
                assert contract['retained_target']['unit_family'] == 'percentage'
                assert {(item['field'], item['retained_value']) for item in contract['binding_ineligibility']} == {
                    ('unit_family', 'percentage'), ('unit', 'percent')}
                instructions = messages[-1]['content']
                assert 'Unaudited is an affirmative source conclusion' in instructions
                assert 'no audited or unaudited binding option' in instructions
                if self.drafts == 2:
                    status_issue = next(item for item in payload['validation_issues'] if item['field'] == 'status')
                    assert status_issue['expected']['allowed_dispositions'] == ['unresolved']
                    assert 'accepts neither audited nor unaudited' in status_issue['message']
                    assert 'unresolved_observation_ids' in status_issue['message']
            if self.drafts == 1 or self.ignore_eligibility:
                return schema(bindings=[self.binding])
            return schema(bindings=[], unresolved_observation_ids=['ratio'],
                unresolved_reason='The retained 3.1% share is outside amount binding; no direct assurance chain is supplied.')
        assert schema is AuditScopeReview
        assert self.drafts >= 2  # Python never converts the first ineligible binding into a reviewed unknown.
        return schema(verdicts=[], unresolved_accepted=self.accept_unknown,
            unresolved_reason='The ratio has no supported amount binding.' if self.accept_unknown
            else 'The proposed unknown explanation needs source-specific support.')


def test_percentage_unaudited_guess_is_corrected_by_model_and_unknown_is_independently_accepted():
    result, binding = percentage_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    gateway = PercentageGateway(binding)
    review_report_audit_scope(gateway, result)
    require_report_audit_scope(result)
    assert gateway.calls == [AuditScopeDraft, AuditScopeDraft, AuditScopeReview]
    assert not reviewed_audit_bindings(result)
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['draft']['unresolved_observation_ids'] == ['ratio']
    assert audit['review']['unresolved_accepted'] is True
    assert (result.document, result.observations, result.analysis_results) == original


@pytest.mark.parametrize('ignore_eligibility,accept_unknown,expected_calls', [
    (True, True, [AuditScopeDraft, AuditScopeDraft]),
    (False, False, [AuditScopeDraft, AuditScopeDraft, AuditScopeReview, AuditScopeDraft, AuditScopeReview]),
])
def test_ignored_type_restriction_or_rejected_unknown_still_blocks_completion(ignore_eligibility, accept_unknown, expected_calls):
    result, binding = percentage_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    gateway = PercentageGateway(binding, ignore_eligibility=ignore_eligibility, accept_unknown=accept_unknown)
    with pytest.raises(ValueError, match='correction budget exhausted'):
        review_report_audit_scope(gateway, result)
    assert gateway.calls == expected_calls
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    assert not reviewed_audit_bindings(result)
    assert (result.document, result.observations, result.analysis_results) == original


@pytest.mark.parametrize('field,value', [
    ('fact_type', 'derived_fact'), ('ifrs_status', 'NON_IFRS'), ('ifrs_status', 'ADJUSTED'),
    ('unit_family', 'percentage'), ('unit', 'percent'), ('unit', 'ratio'), ('unit', 'multiple'),
])
def test_reusable_eligibility_matches_each_existing_type_restriction(field, value):
    retained = dict(fact_type='reported_fact', ifrs_status='IFRS', unit_family='currency', unit='currency')
    assert audit_binding_ineligibility(retained) == []
    retained[field] = value
    assert [(item['field'], item['retained_value']) for item in audit_binding_ineligibility(retained)] == [(field, value)]
