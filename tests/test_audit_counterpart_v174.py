"""Broad assurance plus a matching summary cannot replace a covered source row."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_batches import validate_review, resumable_batches
from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _validate, review_report_audit_scope,
    reviewed_audit_bindings, require_report_audit_scope,
)
from tests.test_report_audit_scope_v174 import Gateway, covered_source, fixture


def models(binding, proof):
    draft = AuditScopeDraft(bindings=[binding], unresolved_observation_ids=['ratio'],
        unresolved_reason='The percentage has no direct assurance evidence.')
    review = AuditScopeReview(verdicts=[dict(observation_id='amount', accepted=True,
        reason='The exact row, six-month column and unit belong to the covered original table.',
        covered_source=proof)], unresolved_accepted=True,
        unresolved_reason='The ratio itself has no assurance chain.')
    return draft, review


def test_independent_literal_counterpart_and_range_are_required_beyond_true_verdict():
    result, binding = fixture()
    draft, review = models(binding, None)
    _validate(draft, _context(result))  # The former structural contract passes.
    with pytest.raises(ValueError, match='independently covered source table'):
        validate_review(draft, review, _context(result))
    draft, review = models(binding, covered_source(binding))
    validate_review(draft, review, _context(result))


def summary_binding(result, binding):
    binding.update(source_unit='RMB thousands', value_quote=deepcopy(binding['target_quote']),
        header_quote=dict(page=1, text='consolidated results for 6M2025.'),
        unit_quote=dict(page=1, text='Amounts in RMB thousands.'))
    result.document.pages[0].text += '\n1\n'
    return binding


def test_summary_and_same_entity_year_amount_cannot_claim_an_unrelated_covered_page():
    result, binding = fixture()
    summary_binding(result, binding)
    proof = covered_source(binding)
    proof['page_coverage'][0].update(page=1, covered_page_label='1',
                                   page_label_quote=dict(page=1, text='1'))
    draft, review = models(binding, proof)
    _validate(draft, _context(result))
    with pytest.raises(ValueError, match='within the same explicit covered page range'):
        validate_review(draft, review, _context(result))


def test_reviewer_cannot_silently_substitute_a_real_counterpart_for_the_wrong_proposal():
    result, binding = fixture()
    proof = covered_source(binding)
    summary_binding(result, binding)
    draft, review = models(binding, proof)
    with pytest.raises(ValueError, match='exact proposed counterpart page'):
        validate_review(draft, review, _context(result))


@pytest.mark.parametrize('field,text', [
    ('covered_value_quote', 'Revenue 120,463.'),
    ('covered_value_quote', 'Revenue 120,4620.'),
    ('covered_value_quote', 'Other metric 120,462.'),
    ('covered_header_quote', 'Six months ended 30 June 2024.'),
    ('covered_unit_quote', 'USD thousands.'),
])
def test_independent_counterpart_must_retain_exact_literal_value_period_and_unit(field, text):
    result, binding = fixture()
    proof = covered_source(binding)
    proof[field]['text'] = text
    draft, review = models(binding, proof)
    with pytest.raises(ValueError):
        validate_review(draft, review, _context(result))


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'extra'])
def test_every_counterpart_quote_page_needs_one_coverage_proof(mutation):
    result, binding = fixture()
    proof = covered_source(binding)
    if mutation == 'missing':
        # A valid header on a second source page requires its own scope link.
        binding['header_quote']['page'] = proof['covered_header_quote']['page'] = 6
        result.document.pages[5].text = binding['header_quote']['text'] + '\n6\n'
    else:
        entry = deepcopy(proof['page_coverage'][0])
        if mutation == 'extra':
            entry['page'] = 6
        proof['page_coverage'].append(entry)
    draft, review = models(binding, proof)
    with pytest.raises(ValueError, match='every counterpart quote page exactly once'):
        validate_review(draft, review, _context(result))


@pytest.mark.parametrize('mutation', ['range', 'prefix', 'marker', 'embedded', 'scope'])
def test_page_membership_uses_literal_range_and_marker_not_invented_pdf_offsets(mutation):
    result, binding = fixture()
    proof = covered_source(binding)
    page = proof['page_coverage'][0]
    if mutation == 'range':
        page['range_end_label'] = '8'
    elif mutation == 'prefix':
        page['covered_page_label'] = 'II-5'
    elif mutation == 'marker':
        page['page_label_quote']['text'] = 'Invented page 5'
    elif mutation == 'embedded':
        result.document.pages[4].text = result.document.pages[4].text.replace('\n5\n', '')
    else:
        page['scope_quote'] = dict(page=5, text='Example Group consolidated results.')
    draft, review = models(binding, proof)
    with pytest.raises(ValueError):
        validate_review(draft, review, _context(result))


def test_printed_appendix_range_is_checked_without_assuming_pdf_page_offsets():
    result, binding = fixture()
    scope = binding['scope_evidence'][0]['text'].replace('pages 5 to 7', 'pages I-3 to I-81')
    binding['scope_evidence'][0]['text'] = result.document.pages[3].text = scope
    result.document.pages[4].text = result.document.pages[4].text.replace('\n5\n', '\n– I-10 –\n')
    proof = covered_source(binding)
    proof['page_coverage'][0].update(range_start_label='I-3', range_end_label='I-81',
        covered_page_label='I-10', page_label_quote=dict(page=5, text='– I-10 –'))
    draft, review = models(binding, proof)
    validate_review(draft, review, _context(result))


def test_original_observation_may_itself_be_the_covered_original_table():
    result, binding = fixture()
    amount = result.observations[0]
    amount.evidence[0].page = 5
    result.profile.source_coverage.checks[0].pages.append(1)
    binding['target_quote'] = deepcopy(binding['value_quote'])
    raw = deepcopy((result.document, result.observations, result.analysis_results))
    review_report_audit_scope(Gateway(binding), result)
    require_report_audit_scope(result)
    assert set(reviewed_audit_bindings(result)) == {'amount'}
    assert (result.document, result.observations, result.analysis_results) == raw


@pytest.mark.parametrize('status', ['audited', 'unaudited'])
def test_direct_table_qualification_needs_literal_same_page_scope_and_no_range_guess(status):
    result, binding = fixture()
    declaration = f'Example Group: this six-month table is {status}.'
    result.document.pages[4].text += '\n' + declaration
    binding.update(status=status, scope_evidence=[dict(page=5, text=declaration)])
    proof = covered_source(binding)
    proof['page_coverage'] = [dict(page=5, basis='direct_table_qualification',
                                 scope_quote=dict(page=5, text=declaration))]
    draft, review = models(binding, proof)
    _validate(draft, _context(result))
    validate_review(draft, review, _context(result))
    review.verdicts[0].covered_source.page_coverage[0].scope_quote.page = 4
    with pytest.raises(ValueError):
        validate_review(draft, review, _context(result))


def test_old_true_verdicts_cannot_survive_accepted_gate_or_completed_batch_resume():
    result, binding = fixture()
    review_report_audit_scope(Gateway(binding), result)
    warning = result.validation_warnings[-1]
    audit = json.loads(warning.message)
    for item in [audit['review'], *[batch['review'] for batch in audit['batches']]]:
        for verdict in item['verdicts']:
            verdict.pop('covered_source')
    warning.message = json.dumps(audit)
    assert not reviewed_audit_bindings(result)
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    warning.code = 'report_audit_scope_unresolved'
    assert resumable_batches(result, audit['context']) == {}


def test_repeated_boolean_only_review_exhausts_semantic_correction_and_never_accepts():
    result, binding = fixture()
    class MissingProof(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            value = super().generate_structured(messages, schema, **kwargs)
            if schema is AuditScopeReview:
                value.verdicts[0].covered_source = None
            return value
    gateway = MissingProof(binding)
    with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
        review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 4
    assert not reviewed_audit_bindings(result)


def test_empty_direct_scope_cannot_be_literal_evidence():
    result, binding = fixture()
    proof = covered_source(binding)
    proof['page_coverage'] = [dict(page=5, basis='direct_table_qualification',
                                 scope_quote=dict(page=5, text='        '))]
    draft, review = models(binding, proof)
    with pytest.raises(ValueError, match='literal proposed scope evidence'):
        validate_review(draft, review, _context(result))


def test_old_request_capacity_splits_do_not_preempt_the_new_smaller_proof_contract():
    from tests.test_report_audit_batches_v174 import (
        BatchGateway, SplittingGateway, many_targets, _failed_first_checkpoint,
    )
    result, binding = many_targets(3)
    review_report_audit_scope(SplittingGateway(binding), result)
    prior = _failed_first_checkpoint(result)
    prior['request_strategy'] = 'audit-scope-full-sources-v174'
    result.validation_warnings[-1].message = json.dumps(prior)
    gateway = BatchGateway(binding)
    review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 2
    assert len(gateway.groups) == 1 and len(gateway.groups[0]) == 3
    require_report_audit_scope(result)
