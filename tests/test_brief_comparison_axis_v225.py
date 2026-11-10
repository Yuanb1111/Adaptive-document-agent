"""An asymmetric comparison uses its stated baseline, not chronological order."""
import pytest

from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview, meaning_validator
from adaptive_document_agent.models.executive_brief import BriefQuote, ExecutiveBrief, ExecutiveBriefItem
from tests.test_brief_direction_v174 import Gateway
from tests.test_executive_brief import result_for


@pytest.mark.parametrize('signed', [False, True])
@pytest.mark.parametrize('reverse_binding', [False, True])
def test_earlier_lower_than_later_keeps_reference_and_subject_endpoints(signed, reverse_binding):
    measure = 'Loss magnitude' if signed else 'Expense'
    values = ('(5,845)', '(13,665)') if signed else ('5,845', '13,665')
    source = f'{measure} (USD thousand): FY2023 {values[0]}; FY2024 {values[1]}.'
    claim = f'{measure} was lower in FY2023 than FY2024.'
    start, end = values if reverse_binding else tuple(reversed(values))
    review = BriefMeaningReview(items=[dict(index=0, accepted=True, reason='Owned source checked.',
        numeric_comparison=True, comparisons=[dict(claim=claim, start_value=start, end_value=end,
            direction='increase' if reverse_binding else 'decrease', absolute_magnitude=signed,
            start_ref='i0_q0', end_ref='i0_q0', start_duration_months=12, end_duration_months=12)])])
    direction = BriefClaimDirectionReview(items=[dict(index=0, comparisons=[dict(
        comparison_index=0, claim=claim, predicate='was lower', direction='decrease',
        absolute_magnitude=signed, reason='The earlier subject is lower than its later reference.')])])
    brief = ExecutiveBrief(items=[ExecutiveBriefItem(label=measure, text=claim,
        evidence=[BriefQuote(page=1, text=source)])])
    failures = meaning_validator(Gateway(review, direction), result=result_for([source]))(brief)
    assert bool(failures) is reverse_binding


def test_a_wrong_lower_than_statement_still_fails_source_arithmetic():
    source = 'Expense (USD thousand): FY2023 13,665; FY2024 5,845.'
    claim = 'Expense was lower in FY2023 than FY2024.'
    review = BriefMeaningReview(items=[dict(index=0, accepted=True, reason='Source review.',
        numeric_comparison=True, comparisons=[dict(claim=claim, start_value='5,845', end_value='13,665',
            direction='decrease', start_ref='i0_q0', end_ref='i0_q0',
            start_duration_months=12, end_duration_months=12)])])
    brief = ExecutiveBrief(items=[ExecutiveBriefItem(label='Expense', text=claim,
        evidence=[BriefQuote(page=1, text=source)])])
    errors = meaning_validator(Gateway(review, None), result=result_for([source]))(brief)
    assert any('direction contradicts its source-bound endpoints' in error for error in errors[0])
