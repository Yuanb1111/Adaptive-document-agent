"""Multiline header correction retains literal intervening text AND the year."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.audit_header_feedback import header_reading_windows
from adaptive_document_agent.agent.report_audit_correction import correction_messages, target_contracts
from adaptive_document_agent.agent.report_audit_scope import (
    AuditBindingValidationError, AuditScopeDraft, AuditScopeReview, _context, _validate,
    require_report_audit_scope, review_report_audit_scope, reviewed_audit_bindings,
)
from tests.test_report_audit_scope_v174 import fixture, covered_source


HEADER = ('                                      Six months ended\n'
          '       Year ended 31 December             30 June\n\n'
          'Notes     2026    2027    2028    2027    2028')


def multiline_case():
    result, binding = fixture()
    for page in result.document.pages:
        page.text = page.text.replace('6M2025', 'FY2027').replace(
            'six months ended 30 June 2025', 'year ended 31 December 2027')
    for observation in result.observations:
        observation.period = 'FY2027'
    result.presentation_plan.themes[0].caveats = ['FY2027 audit status is unknown.']
    result.document.pages[4].text = (
        'Example Group consolidated results.\n' + HEADER + '\n\n'
        'RMB’000   RMB’000   RMB’000   RMB’000   RMB’000\n'
        '                                (Unaudited)\n'
        'Revenue 100,000 120,462 140,000 60,000 70,000\n5\n')
    binding.update(period='FY2027', target_quote=dict(page=1, text=result.document.pages[0].text),
        value_quote=dict(page=5, text='Revenue 100,000 120,462 140,000 60,000 70,000'),
        header_quote=dict(page=5, text=HEADER),
        unit_quote=dict(page=5, text='RMB’000   RMB’000   RMB’000   RMB’000   RMB’000'),
        scope_evidence=[dict(page=4, text=result.document.pages[3].text)])
    return result, binding


def draft_for(binding):
    return AuditScopeDraft(bindings=[binding], unresolved_observation_ids=['ratio'],
                           unresolved_reason='The ratio is outside amount assurance.')


@pytest.mark.parametrize('bad_header', [
    'Year ended 31 December\nNotes     2026    2027    2028    2027    2028',
    'Year ended 31 December             30 June',
])
def test_feedback_supplies_contiguous_header_and_preserves_both_constraints(bad_header):
    result, binding = multiline_case()
    binding['header_quote']['text'] = bad_header
    draft = draft_for(binding)
    context = _context(result)
    original = deepcopy((context, draft))
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft, context)
    entry = dict(draft=draft.model_dump(mode='json'), error=str(raised.value),
                 validation_issues=raised.value.issues)
    messages = correction_messages(context, draft, entry)
    contract = next(c for c in entry['correction_contracts'] if c['observation_id'] == 'amount')
    feedback = contract['header_reading_windows']
    assert feedback['required_period'] == 'FY2027'
    assert feedback['assurance_established'] is False
    assert feedback['full_source_pages_retained'] is True
    assert len(feedback['windows']) == 1
    window = feedback['windows'][0]
    page = result.document.pages[window['page'] - 1].text
    assert page[window['start_char']:window['end_char']] == window['text']
    assert HEADER in window['text'] and '(Unaudited)' in window['text']
    assert 'BOTH' in messages[-1]['content']
    assert messages[-2]['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n')
    assert (context, draft) == original
    # Reading assistance never turns the original invalid proposal into approval.
    with pytest.raises(AuditBindingValidationError):
        _validate(draft, context)


@pytest.mark.parametrize('reject_corrected', [False, True])
def test_unknown_then_malformed_header_can_recover_within_existing_budget(reject_corrected):
    result, valid = multiline_case()
    original = deepcopy((result.document, result.observations))
    bad = deepcopy(valid)
    bad['header_quote']['text'] = 'Year ended 31 December\nNotes 2026 2027 2028 2027 2028'

    class Gateway:
        drafts = 0
        reviews = 0

        def generate_structured(self, messages, schema, **kwargs):
            if schema is AuditScopeDraft:
                self.drafts += 1
                if self.drafts == 1:
                    return schema(unresolved_observation_ids=['amount', 'ratio'],
                                  unresolved_reason='No covered counterpart found.')
                if self.drafts == 2:
                    return draft_for(bad)
                assert self.drafts == 3
                feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                contract = next(c for c in feedback['target_contracts'] if c['observation_id'] == 'amount')
                window = contract['header_reading_windows']['windows'][0]['text']
                assert HEADER in window
                # Controlled model response: select the original complete header.
                # This verifies orchestration, not live-model semantic quality.
                corrected = deepcopy(valid)
                corrected['header_quote']['text'] = window[window.index(HEADER):][:len(HEADER)]
                return draft_for(corrected)
            assert schema is AuditScopeReview
            self.reviews += 1
            if self.reviews == 1:
                return schema(verdicts=[], unresolved_accepted=False,
                    unresolved_reason='Amount has a covered FY2027 counterpart on page 5; recheck the full grid.')
            return schema(verdicts=[dict(observation_id='amount', accepted=not reject_corrected,
                covered_source=covered_source(valid) if not reject_corrected else None,
                reason='Wrong column ownership.' if reject_corrected else 'Exact amount and period are covered.')],
                unresolved_accepted=True, unresolved_reason='Ratio stays outside amount assurance.')

    gateway = Gateway()
    if reject_corrected:
        with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
            review_report_audit_scope(gateway, result)
        assert not reviewed_audit_bindings(result)
    else:
        review_report_audit_scope(gateway, result)
        require_report_audit_scope(result)
        assert set(reviewed_audit_bindings(result)) == {'amount'}
    assert gateway.drafts == 3 and gateway.reviews == 2
    record = json.loads(result.validation_warnings[-1].message)['batches'][0]
    assert record['corrections_used']['binding_validation'] == 1
    assert record['corrections_used']['independent_review'] == 1
    assert (result.document, result.observations) == original


def test_missing_year_or_unavailable_proposed_page_does_not_invent_a_window():
    result, binding = multiline_case()
    draft = draft_for(binding)
    context = _context(result)
    context['source_pages'] = [dict(page=6, text=HEADER)]
    assert not header_reading_windows(context, draft.bindings[0], 'FY2027')['windows']
    context['source_pages'] = [dict(page=5, text=HEADER.replace('2027', '2029'))]
    assert not header_reading_windows(context, draft.bindings[0], 'FY2027')['windows']
    assert target_contracts(context)[0]['header_quote']['required_period'] == 'FY2027'


def test_reading_aids_are_bounded_and_never_truncate_source_lines():
    _, binding = multiline_case()
    draft = draft_for(binding)
    text = '\n'.join('2027 ' + ('x' * 2000) for _ in range(12))
    context = dict(source_pages=[dict(page=5, text=text)])
    feedback = header_reading_windows(context, draft.bindings[0], 'FY2027')
    assert not feedback['windows'] and feedback['omitted_windows'] == 12
    text = '\n'.join(f'2027 {i}' for i in range(12))
    context['source_pages'][0]['text'] = text
    feedback = header_reading_windows(context, draft.bindings[0], 'FY2027')
    assert len(feedback['windows']) == 4 and feedback['omitted_windows'] > 0
    assert all(w['text'] == text[w['start_char']:w['end_char']] for w in feedback['windows'])
