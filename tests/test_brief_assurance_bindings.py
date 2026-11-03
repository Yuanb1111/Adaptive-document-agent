"""A mixed source page needs exact semantic scope, never blanket assurance."""
import pytest

from adaptive_document_agent.agent.brief_assurance_bindings import assurance_catalog
from adaptive_document_agent.agent.brief_audit_scope import audit_status_errors, source_audit_scope
from tests.test_brief_status_ownership_v148 import mixed_tables


def case():
    result, brief = mixed_tables()
    item = brief.items[0]
    item.text = ('Programme fees were USD1,250 thousand in unaudited 6M2023. '
                 'Programme prices were USD6 thousand per unit in 6M2023.')
    inventory = source_audit_scope(item, result)
    catalog = assurance_catalog(inventory)
    ref = next(key for key, row in catalog.items() if row['table_id'] == 'fees'
               and row['period'] == '6M2023')
    binding = dict(claim=item.text.split('. ')[0], status='unaudited', source_refs=[ref])
    return result, item, inventory, catalog, binding


def test_supported_measure_does_not_inherit_unknown_from_another_quoted_table():
    result, item, inventory, catalog, binding = case()
    assert audit_status_errors(item, result, inventory=inventory)
    assert not audit_status_errors(item, result, inventory=inventory, bindings=[binding])
    assert catalog[binding['source_refs'][0]]['row_labels'] == ['Programme fees']
    assert any(row['status'] == 'unknown' for row in catalog.values())


@pytest.mark.parametrize('change', ['unknown', 'other_period', 'missing_id', 'duplicate', 'unbound_clause', 'status'])
def test_bad_scope_choices_cannot_authorize_an_assertion(change):
    result, item, inventory, catalog, binding = case()
    if change == 'unknown':
        binding['source_refs'] = [next(key for key, row in catalog.items()
                                      if row['table_id'] == 'unit-prices' and row['period'] == '6M2023')]
    elif change == 'other_period':
        binding['source_refs'] = [next(key for key, row in catalog.items() if row['period'] == '6M2024')]
    elif change == 'missing_id':
        binding['source_refs'] = ['not-in-this-item']
    elif change == 'duplicate':
        binding['source_refs'] *= 2
    elif change == 'unbound_clause':
        binding['claim'] = 'An unrelated sentence.'
    else:
        binding['status'] = 'audited'
    assert audit_status_errors(item, result, inventory=inventory, bindings=[binding])


def test_copy_contract_can_defer_only_a_supported_mixed_scope_to_fresh_review():
    result, item, inventory, _, _ = case()
    assert not audit_status_errors(item, result, inventory=inventory, defer_scope_review=True)
    # Deferral grants no final approval: no binding still fails the real gate.
    assert audit_status_errors(item, result, inventory=inventory)
    item.text = item.text.replace('unaudited', 'audited')
    assert audit_status_errors(item, result, inventory=inventory, defer_scope_review=True)


def test_independent_review_rejection_still_wins_with_a_valid_assurance_binding():
    from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview
    from adaptive_document_agent.agent.brief_meaning_evidence import review_evidence_errors
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    result, item, inventory, _, binding = case()
    response = BriefMeaningReview(items=[dict(index=0, accepted=False,
        reason='Independent source review rejects another false claim.', numeric_comparison=False,
        comparisons=[], assurance_bindings=[binding])])
    failures = review_evidence_errors(response, brief=ExecutiveBrief(items=[item]),
        pending=[dict(index=0, source_audit_scope=inventory)], catalogs={0: {}}, result=result)
    assert failures == {0: ['Independent source review rejects another false claim.']}


@pytest.mark.parametrize('use_unknown_source', [False, True])
def test_real_review_path_requires_owned_assurance_references(use_unknown_source):
    from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    from tests.test_executive_brief import gateway
    result, item, _, catalog, binding = case()
    if use_unknown_source:
        binding['source_refs'] = [next(key for key, row in catalog.items()
            if row['table_id'] == 'unit-prices' and row['period'] == '6M2023')]
    g, client = gateway([dict(items=[dict(index=0, accepted=True, reason='Source scope reviewed.',
        numeric_comparison=False, comparisons=[], assurance_bindings=[binding])])])
    errors = meaning_validator(g, result=result)(ExecutiveBrief(items=[item]))
    assert bool(errors) is use_unknown_source
    assert 'source_assurance_catalog' in client.calls[0][1]['content']
