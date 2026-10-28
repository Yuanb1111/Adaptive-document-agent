"""Short printed markers preserve evidence without bypassing assurance review."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.report_audit_batches import validate_review
from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _review_batch, _validate,
)
from adaptive_document_agent.models.executive_brief import BriefQuote
from tests.test_budget_output_v145 import gateway, response
from tests.test_report_audit_scope_v174 import covered_source, fixture


def marker_case(marker='– I-5 –', label='I-5', start='I-3', end='I-9'):
    result, binding = fixture()
    scope = binding['scope_evidence'][0]['text'].replace('5 to 7', f'{start} to {end}')
    binding['scope_evidence'][0]['text'] = scope
    result.document.pages[3].text = scope
    result.document.pages[4].text = result.document.pages[4].text.replace('\n5\n', f'\n{marker}\n')
    binding['scope_evidence'].append(dict(page=5, text=marker))
    draft = dict(bindings=[binding], unresolved_observation_ids=['ratio'],
        unresolved_reason='The percentage has no independently supported amount assurance.')
    counterpart = covered_source(binding)
    counterpart['page_coverage'][0].update(range_start_label=start, range_end_label=end,
        covered_page_label=label, page_label_quote=dict(page=5, text=marker))
    review = AuditScopeReview(verdicts=[dict(observation_id='amount', accepted=True,
        reason='The exact row, period and unit lie within the independently confirmed scope.',
        covered_source=counterpart)], unresolved_accepted=True,
        unresolved_reason='Amount assurance does not transfer to the percentage.')
    return result, draft, review


@pytest.mark.parametrize('marker,label,start,end', [
    ('– I-5 –', 'I-5', 'I-3', 'I-9'), ('5', '5', '5', '7'),
    ('(A-2)', 'A-2', 'A-1', 'A-9'), ('42', '42', '40', '44'),
])
def test_short_scope_marker_survives_schema_and_exact_source_coverage(marker, label, start, end):
    result, raw, review = marker_case(marker, label, start, end)
    context = _context(result)
    original = deepcopy((raw, context))
    draft = AuditScopeDraft.model_validate(raw)
    _validate(draft, context)
    validate_review(draft, review, context)
    assert draft.bindings[0].scope_evidence[-1].text == marker
    assert draft.model_dump() == raw
    assert (raw, context) == original


@pytest.mark.parametrize('text', ['', '       ', 'audited', 'Group', '– –'])
def test_scope_quote_exception_does_not_allow_empty_or_short_prose(text):
    _, raw, _ = marker_case()
    raw['bindings'][0]['scope_evidence'][-1]['text'] = text
    with pytest.raises(ValidationError):
        AuditScopeDraft.model_validate(raw)


@pytest.mark.parametrize('mutation', ['missing', 'inline', 'wrong_page', 'missing_page'])
def test_short_marker_must_be_a_literal_standalone_line_on_its_cited_page(mutation):
    result, raw, _ = marker_case()
    if mutation == 'missing':
        result.document.pages[4].text = result.document.pages[4].text.replace('– I-5 –', '– I-6 –')
    elif mutation == 'inline':
        result.document.pages[4].text = result.document.pages[4].text.replace('– I-5 –', 'See – I-5 – for details.')
    else:
        raw['bindings'][0]['scope_evidence'][-1]['page'] = 4 if mutation == 'wrong_page' else 999
    with pytest.raises(ValueError, match='literal standalone printed page marker'):
        _validate(AuditScopeDraft.model_validate(raw), _context(result))


@pytest.mark.parametrize('field', ['target_quote', 'value_quote', 'header_quote'])
def test_prose_quote_fields_keep_their_existing_length_contract(field):
    _, raw, _ = marker_case()
    raw['bindings'][0][field]['text'] = '– I-5 –'
    with pytest.raises(ValidationError):
        AuditScopeDraft.model_validate(raw)
    with pytest.raises(ValidationError):
        BriefQuote(page=5, text='– I-5 –')


def test_short_complete_unit_is_preserved_in_writer_and_independent_review():
    result, raw, review = marker_case()
    raw['bindings'][0]['unit_quote']['text'] = 'RMB’000'
    review.verdicts[0].covered_source.covered_unit_quote.text = 'RMB’000'
    draft = AuditScopeDraft.model_validate(raw)
    review = AuditScopeReview.model_validate_json(review.model_dump_json())
    context = _context(result)
    _validate(draft, context)
    validate_review(draft, review, context)
    assert draft.bindings[0].unit_quote.text == 'RMB’000'
    assert review.verdicts[0].covered_source.covered_unit_quote.text == 'RMB’000'


@pytest.mark.parametrize('text', ['', '       '])
def test_empty_unit_evidence_is_rejected_in_both_schemas(text):
    _, raw, review = marker_case()
    raw['bindings'][0]['unit_quote']['text'] = text
    with pytest.raises(ValidationError):
        AuditScopeDraft.model_validate(raw)
    reviewed = review.model_dump()
    reviewed['verdicts'][0]['covered_source']['covered_unit_quote']['text'] = text
    with pytest.raises(ValidationError):
        AuditScopeReview.model_validate(reviewed)


@pytest.mark.parametrize('mutation', ['nonliteral', 'scale', 'currency', 'reviewer_unit'])
def test_short_units_still_require_literal_matching_scale_and_currency(mutation):
    result, raw, review = marker_case()
    binding = raw['bindings'][0]
    binding['unit_quote']['text'] = 'RMB’000'
    if mutation == 'nonliteral':
        binding['unit_quote']['text'] = 'USD’000'
    elif mutation == 'scale':
        binding['source_unit_scale'] = 1
    elif mutation == 'currency':
        binding['source_currency'] = 'USD'
    else:
        review.verdicts[0].covered_source.covered_unit_quote.text = 'RMB'
    draft = AuditScopeDraft.model_validate(raw)
    with pytest.raises(ValueError):
        _validate(draft, _context(result))
        validate_review(draft, review, _context(result))


@pytest.mark.parametrize('mutation', ['no_counterpart', 'wrong_label', 'outside_range', 'marker_only'])
def test_marker_never_substitutes_for_independent_covered_counterpart(mutation):
    result, raw, review = marker_case()
    if mutation == 'no_counterpart':
        review.verdicts[0].covered_source = None
    elif mutation == 'wrong_label':
        review.verdicts[0].covered_source.page_coverage[0].covered_page_label = 'I-6'
    elif mutation == 'outside_range':
        review.verdicts[0].covered_source.page_coverage[0].range_end_label = 'I-4'
    else:
        raw['bindings'][0]['scope_evidence'] = raw['bindings'][0]['scope_evidence'][-1:]
    draft = AuditScopeDraft.model_validate(raw)
    with pytest.raises(ValueError):
        _validate(draft, _context(result))
        validate_review(draft, review, _context(result))


def test_out_of_range_feedback_identifies_the_actual_page_and_requires_new_evidence():
    result, raw, review = marker_case()
    review.verdicts[0].covered_source.page_coverage[0].range_end_label = 'I-4'
    with pytest.raises(ValueError) as failure:
        validate_review(AuditScopeDraft.model_validate(raw), review, _context(result))
    message = str(failure.value)
    assert "Physical page 5: covered_page_label='I-5'" in message
    assert "claimed range='I-3' to 'I-4'" in message
    assert 'different exact covered source row' in message
    assert 'unresolved disposition' in message


@pytest.mark.parametrize('accepted', [True, False])
def test_real_gateway_third_draft_reaches_fresh_independent_review(accepted):
    """Binding error -> rejected unknown -> short-marker draft, with no fourth draft."""
    import json
    from adaptive_document_agent.services.llm.config import PrivacyMode

    result, raw, final_review = marker_case()
    invalid = deepcopy(raw)
    invalid['bindings'][0]['header_quote']['text'] = 'No reporting period here.'
    unknown = AuditScopeDraft(unresolved_observation_ids=['amount', 'ratio'],
        unresolved_reason='No labeled counterpart has been established for these targets.')
    rejected_unknown = AuditScopeReview(verdicts=[], unresolved_accepted=False,
        unresolved_reason='The source page contains an exact labeled amount counterpart within scope.')
    if not accepted:
        final_review.verdicts[0].accepted = False
        final_review.verdicts[0].reason = 'The proposed assurance ownership is not supported.'
    llm, client = gateway([response(json.dumps(invalid)), response(unknown), response(rejected_unknown),
                           response(json.dumps(raw)), response(final_review)])
    llm.settings.privacy_mode = PrivacyMode.LOCAL_ONLY
    context, record = _context(result), dict(attempts=[])
    original = deepcopy((context, result.document, result.observations, result.analysis_results))
    if accepted:
        _review_batch(llm, context, record)
        assert record['status'] == 'complete'
        assert record['draft'] == raw
    else:
        with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
            _review_batch(llm, context, record)
        assert 'status' not in record and 'draft' not in record
    assert len(client.requests) == 5
    assert len(record['attempts']) == record['correction_limits']['max_drafts'] == 3
    assert record['corrections_used'] == dict(draft_output=0, binding_validation=1,
        independent_review=1, review_output=0)
    assert record['attempts'][-1]['draft'] == raw
    assert record['attempts'][-1]['review'] == final_review.model_dump()
    assert all(any('short literal standalone printed page marker' in message['content']
                   for message in call[0]) for call in client.requests)
    assert (context, result.document, result.observations, result.analysis_results) == original
