"""Missing counterpart labels/amounts never become instructions to invent a row."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.audit_value_feedback import value_reading_windows
from adaptive_document_agent.agent.report_audit_correction import correction_messages
from adaptive_document_agent.agent.report_audit_scope import (
    AuditBindingValidationError, AuditScopeDraft, AuditScopeReview, _context, _validate,
    review_report_audit_scope, require_report_audit_scope, reviewed_audit_bindings,
)
from tests.test_audit_binding_feedback_v174 import source_case


def missing_counterpart(*, missing_amount=False):
    result, valid, _ = source_case()
    page = result.document.pages[4]
    page.text = ('Example Group consolidated results. Six months ended 30 June 2025. RMB’000.\n'
                 'Expense adjustments\nLine A (60,000)\nLine B (7,618)\n'
                 + ('' if missing_amount else '      (67,618)\n') + 'Working capital movements\n5\n')
    bad = deepcopy(valid)
    bad['value_quote']['text'] = ('Line A (60,000)\nLine B (7,618)' if missing_amount else '      (67,618)')
    bad['unit_quote']['text'] = 'RMB’000.'
    draft = AuditScopeDraft(bindings=[bad], unresolved_observation_ids=['ratio'],
                           unresolved_reason='Ratio is outside amount assurance.')
    return result, draft


@pytest.mark.parametrize('missing_amount', [False, True])
def test_literal_windows_expose_missing_label_or_aggregate_without_inventing_evidence(missing_amount):
    result, draft = missing_counterpart(missing_amount=missing_amount)
    context = _context(result)
    original = deepcopy((context, draft))
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft, context)
    issues = raised.value.issues
    assert all(isinstance(issue['expected'], dict) for issue in issues)
    assert len(issues) == (2 if missing_amount else 1)
    entry = dict(draft=draft.model_dump(mode='json'), error=str(raised.value), validation_issues=issues)
    messages = correction_messages(context, draft, entry)
    aid = entry['correction_contracts'][0]['value_reading_windows']
    assert aid['metric_literal_on_proposed_page'] is False
    assert aid['assurance_established'] is False
    assert aid['semantic_correspondence_established'] is False
    assert aid['full_source_pages_retained'] is True
    assert len(aid['windows']) == (0 if missing_amount else 1)
    for window in aid['windows']:
        assert result.document.pages[4].text[window['start_char']:window['end_char']] == window['text']
        assert 'Cost of sales' not in window['text']
        assert window['amount_line'].strip() == '(67,618)'
    assert 'editable proposed counterpart label' in messages[-1]['content']
    assert 'neighboring label does not name an unlabeled row' in messages[-1]['content']
    assert messages[-2]['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>')
    assert (context, draft) == original


@pytest.mark.parametrize('reject_unknown', [False, True])
def test_model_can_choose_unknown_but_independent_review_is_still_required(reject_unknown):
    result, bad = missing_counterpart()
    original = deepcopy((result.document, result.observations))

    class Gateway:
        drafts = 0
        reviews = 0

        def generate_structured(self, messages, schema, **kwargs):
            if schema is AuditScopeDraft:
                self.drafts += 1
                if self.drafts == 1:
                    return bad.model_copy(deep=True)
                if self.drafts == 2:
                    feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                    assert feedback['target_contracts'][0]['value_reading_windows']['windows']
                return schema(unresolved_observation_ids=['amount', 'ratio'],
                    unresolved_reason='Page 5 has an unlabeled subtotal only; no literal same-measure '
                                      'labeled counterpart is covered. Ratio is outside amount assurance.')
            self.reviews += 1
            assert schema is AuditScopeReview
            assert 'blank-label subtotal' in messages[0]['content']
            return schema(verdicts=[], unresolved_accepted=not reject_unknown,
                          unresolved_reason='Check other covered pages.' if reject_unknown
                          else 'Full supplied pages have no eligible labeled counterpart for these targets.')

    gateway = Gateway()
    if reject_unknown:
        with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
            review_report_audit_scope(gateway, result)
        assert gateway.drafts == 3 and gateway.reviews == 2
    else:
        review_report_audit_scope(gateway, result)
        require_report_audit_scope(result)
        assert gateway.drafts == 2 and gateway.reviews == 1
    assert not reviewed_audit_bindings(result)
    assert (result.document, result.observations) == original


def test_forged_summary_label_on_another_page_still_fails_without_review():
    result, draft = missing_counterpart()
    draft.bindings[0].value_quote.text = 'Cost of sales (67,618)'
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft, _context(result))
    assert any(i['field'] == 'value_quote' for i in raised.value.issues)


def test_windows_keep_sign_and_numeric_boundaries_and_never_clip_long_rows():
    _, draft = missing_counterpart()
    binding = draft.bindings[0]
    context = dict(source_pages=[dict(page=5, text='67,618\n(167,618)\n(67,618.5)')])
    assert not value_reading_windows(context, binding)['windows']
    context['source_pages'][0]['text'] = '\n'.join('(67,618) ' + 'x' * 1900 for _ in range(6))
    aid = value_reading_windows(context, binding)
    assert not aid['windows'] and aid['omitted_windows'] == 6
    context['source_pages'][0]['text'] = '\n'.join('(67,618)' for _ in range(10))
    aid = value_reading_windows(context, binding)
    assert len(aid['windows']) == 4 and aid['omitted_windows'] == 6
    binding.value_quote.page = 999
    assert not value_reading_windows(context, binding)['proposed_page_available']
    binding.value_quote.page = 5
    binding.source_raw_value = '67,618'
    context['source_pages'][0]['text'] = '−67,618\n(67,618)\n67,618.5\nCost 67,618.'
    aid = value_reading_windows(context, binding)
    assert len(aid['windows']) == 1
    assert aid['windows'][0]['amount_line'] == 'Cost 67,618.'
