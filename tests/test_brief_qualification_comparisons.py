import pytest
from adaptive_document_agent.agent.brief_qualification_comparisons import comparison_options
from adaptive_document_agent.agent.brief_reviewed_qualifications import qualification_quantity_errors


PROOF = ('The proportion of inventories with an age of more than 1 year to the gross inventory balance '
         'increased from 7% to 20%. The proportion with an age of more than 2 years was less than 3%.')
JOINED = ('Inventory movements from December 31, 2021 to June 30, 2024 reflected the expanded business. '
          + PROOF)
SOURCE = dict(page=332, literal_proof=PROOF, typed_quantities=[('', '20', '%')],
              duration_thresholds=[('more than', '1', 'year'), ('more than', '2', 'year')],
              percentage_thresholds=[('less than', '3')])


def options(review='The 20% share needs its June 30, 2024 endpoint.', joined=JOINED):
    return comparison_options({2:{'p332_b14':SOURCE}},
        {2:{'i2_q3':dict(page=332,literal_proof=joined)}}, {2:[review]})[2]


@pytest.mark.parametrize('claim', [
    'By June 30, 2024, inventories aged more than one year rose from 7% to 20% of gross inventory.',
    'June 30, 2024: >1-year stock 20% gross (from 7%); >2-year <3%.',
    'Jun 30, 2024: >1yr 20% gross (vs 7%); >2yr <3%.',
])
def test_only_the_source_comparison_licenses_its_baseline(claim):
    assert not qualification_quantity_errors(claim, 'p332_b14', options())


@pytest.mark.parametrize('claim', [
    'June 30, 2024: 7% of gross inventory was over one year old.',
    'June 30, 2024: >1yr 20% gross (vs 8%).',
    'June 30, 2024: >1yr 7% gross (vs 20%).',
    'June 30, 2024: >1yr 20% net (vs 7%).',
    'June 30, 2024: >1yr 20% of gross revenue (vs 7%).',
    'June 30, 2024: >2yr 20% gross (vs 7%).',
    'June 30, 2024: >1yr stock was monitored, but >2yr was 20% gross (vs 7%).',
    'June 30, 2024: <1yr 20% gross (vs 7%).',
    'June 30, 2024: >1yr gross inventory fell from 7% to 20%.',
    'December 31, 2021: >1yr 20% gross (vs 7%).',
    '>1yr 20% gross (vs 7%).',
    'June 30, 2024: >1yr 20% gross (vs 7%). Another 7% was sold.',
])
def test_changed_period_population_amount_direction_or_separate_quantity_remains_unbound(claim):
    assert qualification_quantity_errors(claim, 'p332_b14', options())


def test_other_source_paragraph_or_review_only_date_cannot_supply_the_comparison_endpoint():
    claim = 'June 30, 2024: >1yr 20% gross (vs 7%).'
    assert qualification_quantity_errors(claim, 'p332_b14', options(review='The 20% needs context.'))
    assert qualification_quantity_errors(claim, 'p332_b14', options(joined='June 30, 2024.\n\n' + PROOF))
