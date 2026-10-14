"""Literal cardinal notation survives translation without weakening evidence checks."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.compact_summary import generate_compact_summary
from adaptive_document_agent.models import CompanyProfile
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief, _quantities
from adaptive_document_agent.services.number_words import cardinal_claim_text, cardinal_numbers
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator as V
from tests.test_compact_summary_v111 import fixture, Reviewer
from tests.test_executive_brief import payload, result_for


@pytest.mark.parametrize('source, digit', [
    ('five models', '5 models'), ('Four-axis models', '4-axis models'),
    ('twenty-two models', '22 models'), ('twenty seven models', '27 models'),
    ('one hundred and five participants', '105 participants'),
    ('nine hundred ninety-nine participants', '999 participants'),
    ('USD five million', 'USD 5 million'), ('negative five percent', '-5 percent'),
    ('minus five units', '-5 units'),
    ('five four-axis models', '5 4-axis models'), ('one and two units', '1 and 2 units'),
])
def test_spelled_cardinals_and_digits_have_the_same_numeric_and_unit_contract(source, digit):
    assert cardinal_claim_text(source) == digit
    assert cardinal_numbers(source) == V._numbers(digit)
    assert _quantities(source) == _quantities(digit)


@pytest.mark.parametrize('text', [
    'someone chose FIVE2 and ModelFive', 'twentyfive participants',
    'one million five hundred participants', 'one hundred hundred participants',
    'twentyfold participants', 'first-class service',
])
def test_names_ordinals_and_unsupported_compounds_do_not_authorize_component_values(text):
    assert cardinal_claim_text(text) == text
    assert not V._numbers(text)


def test_planner_structure_counts_keep_their_existing_observation_contract():
    assert V._numbers('Four series share the same three periods in one table.') == set()
    assert cardinal_numbers('There were five models.') == {'5'}


SOURCE = ('We offered 27 models in four series with payload capacity ranging from 0.25kg to 20kg, '
          'among which 22 were six-axis models and five were four-axis models.')
CLAIM = '提供27款型号，载荷范围0.25kg至20kg，其中22款为六轴型号、5款为四轴型号。'


def brief(source, claim):
    result = result_for([source, 'Other products include 8 models.'])
    value = ExecutiveBrief.model_validate(payload(claim))
    value.items[0].evidence[0].text = source
    return result, value


def test_translated_five_is_literal_support_and_does_not_change_stored_source():
    result, value = brief(SOURCE, CLAIM)
    before = deepcopy(result.model_dump())
    assert not validate_executive_brief(value, result)
    assert result.model_dump() == before
    assert value.items[0].evidence[0].text == SOURCE


@pytest.mark.parametrize('claim', [CLAIM.replace('5款', '8款'), 'There were eight four-axis models.'])
def test_numeric_and_spelled_wrong_counts_cannot_borrow_another_page(claim):
    result, value = brief(SOURCE, claim)
    assert any('unsupported numeric' in e for e in validate_executive_brief(value, result))


@pytest.mark.parametrize('claim', ['There were 5% four-axis models.', 'Revenue was USD5 million.'])
def test_spelled_bare_count_does_not_authorize_an_invented_unit_or_currency(claim):
    result, value = brief('There were five four-axis models.', claim)
    assert validate_executive_brief(value, result)


@pytest.mark.parametrize('source, claim', [
    ('Revenue was USD five million.', 'Revenue was USD5 million.'),
    ('Revenue was USD5 million.', 'Revenue was USD five million.'),
    ('Margin was five percent.', 'Margin was 5%.'),
])
def test_spelled_typed_quantities_preserve_units_in_both_directions(source, claim):
    result, value = brief(source, claim)
    assert not validate_executive_brief(value, result)
    value.items[0].text = claim.replace('million', 'billion').replace('5%', '6%')
    assert validate_executive_brief(value, result)


def compact_fixture():
    result, review, draft = fixture(1)
    source = SOURCE + '\n'
    result.document.pages[0].text = source
    block = review.source_blocks[0]
    block.text, block.char_end = source, len(source)
    part = review.parts[0]
    part.source_text, part.title = source, 'Product range'
    part.facts[0].text = part.facts[0].source_quote = SOURCE
    draft['pages'][0]['title'] = 'Product range'
    draft['pages'][0]['items'][0].update(label='Model range', text=CLAIM)
    return result, review, draft


def test_opening_with_translated_five_reaches_independent_review_without_a_false_repair():
    result, review, draft = compact_fixture()
    client = Reviewer(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.calls == ['CompactSummaryDraft', 'CompactSummaryReview']
    assert company.summary_pages[0].items[0].text == CLAIM


def test_cardinal_equivalence_cannot_bypass_rejected_semantic_association():
    result, review, draft = compact_fixture()
    client = Reviewer(draft, reject='part-0')
    with pytest.raises(ValueError, match='Source meaning is absent'):
        generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert 'CompactSummaryReview' in client.calls


def test_table_header_duration_is_supported_only_in_its_own_complete_date_label():
    from tests.test_brief_table_context import table_result
    result, value = table_result()
    assert not validate_executive_brief(value, result)
    value.items[0].text = value.items[0].text.replace('six months', '6 months')
    assert not validate_executive_brief(value, result)
    for text in ['Customer count was six.', 'Customer count was 6.',
                 'Programme fees were USD 1,475 thousand in the five months ended June 30, 2024.']:
        value.items[0].text = text
        assert validate_executive_brief(value, result)


def test_word_amount_cannot_omit_a_source_denominator():
    from adaptive_document_agent.services.brief_table_evidence import TableQuoteContext
    context = TableQuoteContext(bases={('us$', '5', 'million'): {'employee'}})
    assert context.basis_errors('Revenue was USD five million.')
    assert not context.basis_errors('Revenue was USD five million per employee.')
