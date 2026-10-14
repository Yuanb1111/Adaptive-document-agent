"""Singular counts, shared range units and bounded non-progress corrections."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief, _quantities
from adaptive_document_agent.services.quantity_notation import literal_quantity_text, literal_quantity_numbers
from tests.test_executive_brief import payload, result_for


def check(source, claim):
    result = result_for([source])
    value = ExecutiveBrief.model_validate(payload(claim))
    value.items[0].evidence[0].text = source
    return validate_executive_brief(value, result)


@pytest.mark.parametrize('noun', ['device', 'instrument', 'model', 'participant', 'contract'])
def test_literal_indefinite_singular_can_support_one_but_requires_the_exact_source(noun):
    article = 'an' if noun[0] in 'aeiou' else 'a'
    source = f'The offering includes {article} {noun} and two supporting services.'
    assert not check(source, f'The offering includes one {noun} and two supporting services.')
    assert check(source, f'The offering includes three {noun}s.')


@pytest.mark.parametrize('source', ['Several devices were offered.', 'A few devices were offered.',
                                   'A number of devices were offered.', 'A lot of devices were offered.'])
def test_one_is_not_globally_whitelisted_or_inferred_from_an_indefinite_plural(source):
    assert check(source, 'One device was offered.')


def test_ordinary_article_in_generated_copy_does_not_become_an_extra_numeric_claim():
    assert literal_quantity_numbers('This is a potential interpretation.') == set()
    assert not check('The strategy was described.', 'A strategy was described.')
    assert check('A device was offered.', 'The price was USD1 million.')
    assert check('A device was offered.', 'The margin was 1%.')


@pytest.mark.parametrize('range_text', ['USD8.1–8.4 thousand per unit', 'USD8.1-8.4 thousand/unit',
                                      'USD8.1 to 8.4 thousand per unit', 'RMB8.1–8.4 thousand per unit'])
def test_shared_currency_and_scale_are_parsed_for_both_range_endpoints(range_text):
    currency = range_text[:3]
    assert _quantities(range_text) == {(currency.casefold(), '8.1', 'thousand'),
                                      (currency.casefold(), '8.4', 'thousand')}
    assert not check(f'Prices were {currency}8.1 thousand per unit and {currency}8.4 thousand per unit.',
                     'Prices were ' + range_text + '.')


@pytest.mark.parametrize('claim', ['Prices were USD8.1–8.5 thousand per unit.',
                                  'Prices were RMB8.1–8.4 thousand per unit.',
                                  'Prices were USD8.1–8.4 million per unit.'])
def test_range_cannot_borrow_an_endpoint_currency_or_scale(claim):
    assert check('Prices were USD8.1 thousand per unit and USD8.4 thousand per unit.', claim)


def test_table_range_still_requires_the_full_explicit_denominator_for_both_endpoints():
    from adaptive_document_agent.services.brief_table_evidence import TableQuoteContext
    context = TableQuoteContext(bases={('us$', '8.1', 'thousand'): {'unit'},
                                       ('us$', '8.4', 'thousand'): {'unit'}})
    assert not context.basis_errors('Price was USD8.1–8.4 thousand per unit.')
    assert context.basis_errors('Price was USD8.1–8.4 thousand per day.')
    assert context.basis_errors('Price was USD8.1–8.4 thousand.')


def test_explicit_basis_ends_before_a_quantified_coordinated_item_without_lending_units():
    from adaptive_document_agent.services.brief_table_evidence import TableQuoteContext
    context = TableQuoteContext(bases={('us$', '8.1', 'thousand'): {'unit'},
                                     ('us$', '8.4', 'thousand'): {'unit'}})
    assert not context.basis_errors('Sales were 30 units at USD8.1 thousand/unit and 40 units at USD8.4 thousand/unit.')
    assert context.basis_errors('Sales were 30 units at USD8.1 thousand/unit and 40 units at USD8.4 thousand.')
    assert context.basis_errors('Sales were 30 units at USD8.1 thousand/unit/day and 40 units at USD8.4 thousand/unit.')


def test_source_and_copy_are_not_mutated_by_quantity_notation_checks():
    source = 'The offering includes a device; prices were USD8.1–8.4 thousand per unit.'
    result = result_for([source])
    value = ExecutiveBrief.model_validate(payload('One device was offered; prices were USD8.1–8.4 thousand per unit.'))
    value.items[0].evidence[0].text = source
    before = deepcopy((result.model_dump(), value.model_dump()))
    assert not validate_executive_brief(value, result)
    assert (result.model_dump(), value.model_dump()) == before


@pytest.mark.parametrize('change_on_retry', [True, False])
def test_unchanged_source_repair_gets_one_targeted_protocol_retry_then_stops(change_on_retry):
    from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft
    from adaptive_document_agent.agent.summary_content_repair import revise_content
    original = CompactSummaryDraft(pages=[dict(title='Review', items=[dict(
        label='Count', text='There were 99 devices.', fact_ids=['f0'])])])
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            replacement = original.pages[0].items[0].model_dump()
            if self.calls == 2:
                assert 'changes neither text nor fact IDs' in messages[-1]['content']
                if change_on_retry:
                    replacement['text'] = 'There were two devices.'
            return schema(replacements=[dict(item_id='g0_i0', replacement=replacement)])
    client, audit = Client(), {}
    if change_on_retry:
        revised = revise_content(client, original, [], CompactSummaryDraft, audit,
                                 errors=['Count: unsupported numeric claims 99'], retry_unchanged=True)
        assert revised.pages[0].items[0].text == 'There were two devices.'
    else:
        with pytest.raises(ValueError, match='repeated the rejected draft'):
            revise_content(client, original, [], CompactSummaryDraft, audit,
                           errors=['Count: unsupported numeric claims 99'], retry_unchanged=True)
    assert client.calls == 2
    assert audit['content_revision_attempts'][0]['status'] == 'rejected'


def test_additive_correction_locks_existing_copy_and_rejects_replacements():
    from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft
    from adaptive_document_agent.agent.summary_content_repair import revise_content
    original = CompactSummaryDraft(pages=[dict(title='Conditions', items=[dict(
        label='Delivery', text='The service is available subject to training.', fact_ids=['f0'])])])
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            definition = schema.model_json_schema()['properties']
            assert definition['replacements']['maxItems'] == 0
            assert definition['titles']['maxItems'] == 0
            assert 'ADDITIVE ONLY' in messages[1]['content']
            with pytest.raises(ValueError):
                schema(replacements=[dict(item_id='g0_i0', replacement=original.pages[0].items[0].model_dump())])
            return schema(additions=[dict(group_id='g0', item=dict(label='Conditions',
                text='Delivery timing remains uncertain.', fact_ids=['f1']))])
    audit = {}
    corrected = revise_content(Client(), original, [], CompactSummaryDraft, audit, add_only=True)
    assert corrected.pages[0].title == original.pages[0].title
    assert corrected.pages[0].items[0] == original.pages[0].items[0]
    assert corrected.pages[0].items[1].text == 'Delivery timing remains uncertain.'
    assert audit['content_revision_policy'] == 'additive_meaning_regression'
