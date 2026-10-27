"""One bounded correction sees every independent source-binding defect."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditBindingValidationError, AuditScopeDraft, AuditScopeReview, _context, _validate,
    review_report_audit_scope, require_report_audit_scope,
)
from adaptive_document_agent.agent.report_audit_correction import correction_messages
from tests.test_report_audit_scope_v174 import fixture, covered_source


def source_case():
    result, binding = fixture()
    for page in result.document.pages:
        page.text = page.text.replace('Revenue', 'Cost of sales').replace('120,462', '(67,618)')
    amount = result.observations[0]
    amount.metric_original = 'Cost of sales'
    amount.raw_value = '(67,618)'
    amount.value = -67_618_000
    amount.evidence[0].row_label = 'Cost of sales'
    amount.evidence[0].text = '(67,618)'
    binding['source_metric'] = 'Cost of sales'
    binding['source_raw_value'] = '(67,618)'
    for key in ('target_quote', 'value_quote', 'header_quote', 'unit_quote'):
        binding[key]['text'] = binding[key]['text'].replace('Revenue', 'Cost of sales').replace('120,462', '(67,618)')
    bad = deepcopy(binding)
    bad['target_quote'] = deepcopy(binding['value_quote'])  # Counterpart page, not target observation page.
    bad['value_quote']['text'] = '(67,618)'  # Literal amount alone omits its source row name.
    return result, binding, bad


def test_wrong_target_page_and_missing_source_row_name_are_reported_together():
    result, _, bad = source_case()
    draft = AuditScopeDraft(bindings=[bad], unresolved_observation_ids=['ratio'],
                           unresolved_reason='No direct assurance for the ratio.')
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft, _context(result))
    errors = raised.value.issues
    assert {(issue['observation_id'], issue['field']) for issue in errors} == {
        ('amount', 'target_quote.page'), ('amount', 'value_quote.text')}
    assert errors[0]['expected'] == [1]
    assert errors[1]['expected'] == dict(source_metric_must_be_literal=True,
                                       same_measure_and_signed_amount_required=True)
    assert 'The target quotation must belong to the observation source.' in str(raised.value)
    assert 'The source metric must occur in its quoted source row.' in str(raised.value)


def test_second_draft_can_fix_both_defects_without_an_additional_semantic_attempt():
    result, valid, bad = source_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    class Gateway:
        def __init__(self):
            self.calls = []
            self.drafts = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(schema)
            if schema is AuditScopeDraft:
                self.drafts += 1
                if self.drafts == 2:
                    instructions = messages[-1]['content']
                    assert 'SAME literal quotation' in instructions
                    assert 'heading, introduction' in instructions
                    assert all(field in instructions for field in (
                        'target_quote', 'value_quote', 'header_quote', 'unit_quote', 'scope_evidence',
                        'source_metric', 'source_raw_value', 'source_unit_scale', 'source_currency'))
                    feedback_message = messages[-2]['content']
                    assert feedback_message.startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n')
                    feedback = json.loads(feedback_message.split('\n', 1)[1].rsplit('\n', 1)[0])
                    assert 'amount.target_quote.page' in feedback['validation_or_review_error']
                    assert 'amount.value_quote.text' in feedback['validation_or_review_error']
                    contract = next(item for item in feedback['target_contracts']
                                    if item['observation_id'] == 'amount')
                    assert contract['target_quote'] == dict(allowed_source_pages=[1],
                        required_raw_value='(67,618)', required_row_labels=['Cost of sales'])
                    assert contract['proposed_counterpart_to_recheck']['source_metric'] == 'Cost of sales'
                    assert contract['proposed_counterpart_to_recheck']['source_raw_value'] == '(67,618)'
                assert self.drafts <= 2
                return schema(bindings=[bad if self.drafts == 1 else valid],
                    unresolved_observation_ids=['ratio'], unresolved_reason='No direct assurance for the ratio.')
            assert schema is AuditScopeReview and self.drafts == 2
            return schema(verdicts=[dict(observation_id='amount', accepted=True,
                covered_source=covered_source(valid),
                reason='Own-source row and audited counterpart row retain the exact amount and scope.')],
                unresolved_accepted=True, unresolved_reason='The ratio itself is not covered by amount assurance.')
    gateway = Gateway()
    review_report_audit_scope(gateway, result)
    assert gateway.calls == [AuditScopeDraft, AuditScopeDraft, AuditScopeReview]
    require_report_audit_scope(result)
    audit = json.loads(result.validation_warnings[-1].message)
    first = audit['batches'][0]['attempts'][0]
    assert len(first['validation_issues']) == 2
    assert first['correction_contracts'][0]['target_quote']['required_raw_value'] == '(67,618)'
    assert 'review' not in first  # No independent approval is requested for invalid bindings.
    assert (result.document, result.observations, result.analysis_results) == original


def test_forged_quote_and_wrong_units_remain_independent_hard_errors():
    result, binding, _ = source_case()
    binding['target_quote']['text'] = 'Invented target row for Cost of sales (67,618).'
    binding['source_unit_scale'] = 1
    draft = AuditScopeDraft(bindings=[binding], unresolved_observation_ids=['ratio'],
                           unresolved_reason='No direct assurance for the ratio.')
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft, _context(result))
    assert any(issue['field'] == 'target_quote' for issue in raised.value.issues)
    assert any('source_unit_scale' in issue['field'] for issue in raised.value.issues)


def test_wrong_page_alone_still_repeats_raw_value_and_row_label_contract():
    result, valid, bad = source_case()
    bad['value_quote'] = deepcopy(valid['value_quote'])
    context = _context(result)
    draft = AuditScopeDraft(bindings=[bad], unresolved_observation_ids=['ratio'],
                           unresolved_reason='No direct assurance for the ratio.')
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft, context)
    assert [issue['field'] for issue in raised.value.issues] == ['target_quote.page']
    entry = dict(draft=draft.model_dump(mode='json'), error=str(raised.value),
                 validation_issues=raised.value.issues)
    messages = correction_messages(context, draft, entry)
    target = entry['correction_contracts'][0]['target_quote']
    assert target == dict(allowed_source_pages=[1], required_raw_value='(67,618)',
                         required_row_labels=['Cost of sales'])
    assert 'required_raw_value' in messages[-1]['content']
    assert 'required_row_label' in messages[-1]['content']
    # A literal paragraph from the right page still cannot substitute for the row.
    bad['target_quote'] = dict(page=1, text='Example Group consolidated results for 6M2025.')
    with pytest.raises(AuditBindingValidationError) as missing_row:
        _validate(AuditScopeDraft(bindings=[bad], unresolved_observation_ids=['ratio'],
                  unresolved_reason='No direct assurance for the ratio.'), context)
    assert {issue['message'] for issue in missing_row.value.issues} == {
        'The target quotation must contain its retained raw value.',
        'The target quotation must retain its source row label.'}


def test_target_page_contract_does_not_restrict_counterpart_source_reading():
    from adaptive_document_agent.agent.report_audit_correction import target_contracts
    result, valid, _ = source_case()
    context = _context(result)
    contract = next(c for c in target_contracts(context) if c['observation_id'] == 'amount')
    assert contract['target_quote']['allowed_source_pages'] == [1]
    assert contract['counterpart_quotes']['allowed_source_pages'] == [p['page'] for p in context['source_pages']]
    assert 5 in contract['counterpart_quotes']['allowed_source_pages']
    assert contract['counterpart_quotes']['target_page_restriction_applies'] is False
    _validate(AuditScopeDraft(bindings=[valid], unresolved_observation_ids=['ratio'],
                             unresolved_reason='No amount assurance for ratio.'), context)


def test_unit_spelling_feedback_does_not_treat_model_proposal_as_source():
    result, valid, _ = source_case()
    original = valid['source_unit']
    valid['source_unit'] = 'RMB in thousands'
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(AuditScopeDraft(bindings=[valid], unresolved_observation_ids=['ratio'],
                                 unresolved_reason='Ratio is unresolved.'), _context(result))
    issue = next(i for i in raised.value.issues if i['field'] == 'source_unit/unit_quote.text')
    assert issue['expected']['source_unit_must_be_literal'] is True
    assert 'Both are editable' in issue['message']
    valid['source_unit'] = original
    _validate(AuditScopeDraft(bindings=[valid], unresolved_observation_ids=['ratio'],
                             unresolved_reason='Ratio is unresolved.'), _context(result))
