"""Observed reviewer contradictions must be repaired, never silently approved."""
from copy import deepcopy
import json
from concurrent.futures import CancelledError

import pytest

from adaptive_document_agent.agent.brief_claim_direction import review_claim_directions
from adaptive_document_agent.agent.brief_meaning_review import (
    BriefMeaningReview, MeaningComparison, comparison_errors, meaning_validator,
)
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError, LLMTransportError
from tests.test_brief_direction_repair_v174 import ScriptedGateway, loss_fixture
from tests.test_brief_direction_v174 import observed_loss
from tests.test_executive_brief import result_for


@pytest.mark.parametrize('not_asserted', [False, True])
def test_overlapping_omission_gets_one_source_blind_reconciliation(not_asserted):
    brief, result, source, final = observed_loss(wrong_body=False)
    broken = final.model_copy(deep=True)
    row = broken.items[0]
    row.omitted_directional_claims = [brief.items[0].text.split('(non-IFRS) ')[1]]
    if not_asserted:
        row.comparisons[1].direction = 'not_asserted'
        row.comparisons[1].predicate = ''
    before = brief.model_dump_json()
    gateway = ScriptedGateway([broken.model_dump(), final.model_dump()])
    eligible = set()
    assert review_claim_directions(gateway, brief=brief, verdicts=source.items,
                                   result=result, correction_eligible=eligible) == {}
    assert not eligible and brief.model_dump_json() == before
    retry = gateway.calls[1][0]
    assert retry[:2] == gateway.calls[0][0][:2]
    feedback = json.loads(retry[2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert 'overlaps' in feedback['validation_error']
    assert feedback['previous_response'] == broken.model_dump(mode='json')
    assert 'start_value' not in json.dumps(retry) and 'source_review' not in json.dumps(retry)
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'executive_brief_direction_audit'))
    assert len(audit['attempts']) == 2 and not audit['errors']


def test_persistent_self_contradiction_cannot_certify_a_brief_or_expand_retry_budget():
    brief, result, source, reply = observed_loss(wrong_body=False)
    reply.items[0].omitted_directional_claims = [brief.items[0].label]
    gateway = ScriptedGateway([reply.model_dump(), reply.model_dump()])
    assert 'unavailable' in str(review_claim_directions(
        gateway, brief=brief, verdicts=source.items, result=result))
    assert len(gateway.calls) == 2


def test_reconciliation_cannot_hide_real_false_direction():
    brief, result, source, final = observed_loss(wrong_body=True)
    broken = final.model_copy(deep=True)
    broken.items[0].omitted_directional_claims = [brief.items[0].text]
    gateway = ScriptedGateway([broken.model_dump(), final.model_dump()])
    assert 'direction contradicts' in str(review_claim_directions(
        gateway, brief=brief, verdicts=source.items, result=result))


def test_source_correction_receives_exact_factual_comparison_diagnostics():
    brief, result, source, initial, corrected, final = loss_fixture()
    gateway = ScriptedGateway([source, initial, corrected, final])
    assert meaning_validator(gateway, result=result)(brief) == {}
    payload = json.loads(gateway.calls[2][0][2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    diagnostics = payload['direction_diagnostics']['0']
    for index, row in enumerate(source['items'][0]['comparisons']):
        assert any(f'comparison_index={index}' in diagnostic and row['claim'] in diagnostic
                   for diagnostic in diagnostics)


def percentage_fixture():
    source = 'Gross margin was 50.5% in 2021, 40.8% in 2022 and 43.5% in 2023.'
    item = ExecutiveBriefItem(label='Gross margin recovered but stays below 2021',
        text='Gross margin was 43.5% in 2023 versus 40.8% in 2022 and 50.5% in 2021.',
        evidence=[BriefQuote(page=1, text=source)])
    comparisons = [MeaningComparison(claim=claim, start_value=start, end_value='43.5',
        direction=direction, measure_basis='source_percentage',
        start_context=source, end_context=source, start_duration_months=12, end_duration_months=12)
        for claim, start, direction in [('Gross margin recovered', '40.8', 'increase'),
                                      ('stays below 2021', '50.5', 'decrease')]]
    return item, comparisons


def test_percentage_heading_binds_body_values_but_keeps_separate_directions_and_sources():
    item, comparisons = percentage_fixture()
    source = dict(items=[dict(index=0, accepted=True, reason='Both heading clauses match their source periods.',
        numeric_comparison=True, comparisons=[c.model_dump() for c in comparisons])])
    direction = dict(items=[dict(index=0, comparisons=[dict(comparison_index=i, claim=c.claim,
        predicate='recovered' if i == 0 else 'stays below', direction=c.direction,
        absolute_magnitude=False, reason='The heading predicate describes the stated margin periods.')
        for i, c in enumerate(comparisons)], omitted_directional_claims=[])])
    gateway = ScriptedGateway([source, direction])
    assert meaning_validator(gateway, result=result_for([item.evidence[0].text]))(
        ExecutiveBrief(items=[item])) == {}
    assert not any(comparison_errors(c, item) for c in comparisons)


@pytest.mark.parametrize('mutation', ['body_units', 'source_units', 'money_heading', 'bare_heading',
                                     'body_fragment', 'wrong_direction', 'wrong_endpoint'])
def test_heading_support_cannot_supply_missing_units_or_override_false_values(mutation):
    item, comparisons = percentage_fixture()
    comparison = deepcopy(comparisons[0])
    if mutation == 'body_units':
        item.text = item.text.replace('%', '')
    elif mutation == 'source_units':
        item.evidence[0].text = item.evidence[0].text.replace('%', '')
        comparison.start_context = comparison.end_context = item.evidence[0].text
    elif mutation in {'money_heading', 'bare_heading'}:
        item.label = 'Margin recovered from ' + ('USD40.8 million' if mutation == 'money_heading' else '40.8')
        comparison.claim = item.label
    elif mutation == 'body_fragment':
        item.text += ' Margin recovered from 40.8 to 43.5.'
        comparison.claim = 'Margin recovered from 40.8 to 43.5'
    elif mutation == 'wrong_direction':
        comparison.direction = 'decrease'
    else:
        comparison.start_value = '39.8'
    assert comparison_errors(comparison, item)


@pytest.mark.parametrize('failure', [ValueError('unsupported brief'), PrivacyViolationError('local only'),
                                   CancelledError('stop'), LLMTransportError('offline')])
def test_deferred_brief_failure_is_distinct_from_native_budget_failure(monkeypatch, failure):
    from adaptive_document_agent.agent.brief_budget_schedule import complete_deferred_brief
    from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
    from adaptive_document_agent.agent.presentation_budget_refinement import FinalBudgetBriefError
    result = result_for(['Source statement.'])
    result.executive_brief = None
    def fail(*args):
        raise failure
    monkeypatch.setattr(ExecutiveBriefWriter, 'generate', fail)
    expected = FinalBudgetBriefError if isinstance(failure, (ValueError, LLMTransportError)) else type(failure)
    with pytest.raises(expected):
        complete_deferred_brief(None, result)
    assert result.executive_brief is None
