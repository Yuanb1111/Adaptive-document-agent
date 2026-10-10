"""Arithmetic and reporting-duration gates remain active after semantic repair."""
import json

import pytest

from adaptive_document_agent.agent.brief_meaning_review import MeaningComparison, comparison_errors
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem, BriefQuote
from adaptive_document_agent.models.summary import SummaryFact
from adaptive_document_agent.services.summary_validation import fact_errors
from tests.test_executive_brief import gateway, result_for
from tests.test_brief_table_context import table_result


def comparison(claim='Share fell from 2% to 3%.', **kwargs):
    values = dict(claim=claim, start_value='2%', end_value='3%', direction='decrease',
        start_context='Share was 2% in 2023.', end_context='Share was 3% in 2024.',
        start_duration_months=12, end_duration_months=12)
    return MeaningComparison(**{**values, **kwargs})


def item(text='Share fell from 2% to 3%.'):
    return ExecutiveBriefItem(label='Share', text=text, evidence=[
        BriefQuote(page=1, text='Share was 2% in 2023. Share was 3% in 2024.')])


def test_reviewer_acceptance_cannot_override_arithmetic_or_source_period_duration():
    assert any('direction' in e for e in comparison_errors(comparison(), item()))
    correct = item('Share rose from 2% to 3%.')
    assert not comparison_errors(comparison(correct.text, direction='increase'), correct)
    assert any('durations' in e for e in comparison_errors(
        comparison(correct.text, direction='increase', end_duration_months=6), correct))
    assert any('outside' in e for e in comparison_errors(comparison(start_context='Other share was 2% in 2023.'), item()))


@pytest.mark.parametrize('valid_patch', [True, False])
def test_writer_repairs_only_the_false_comparison_and_rechecks_the_patch(valid_patch):
    original = {'title': 'Shares', 'items': [item().model_dump(mode='json')]}
    corrected = item('Share rose from 2% to 3%.' if valid_patch else 'Share declined from 2% to 3%.')
    wrong_review = {'items': [{'index': 0, 'accepted': True, 'numeric_comparison': True, 'reason': 'Check exact endpoint arithmetic',
                              'comparisons': [comparison().model_dump(mode='json')]}]}
    final_review = {'items': [{'index': 0, 'accepted': True, 'numeric_comparison': True, 'reason': 'Source-bound comparison',
        'comparisons': [comparison(corrected.text, direction='increase' if valid_patch else 'decrease').model_dump(mode='json')]}]}
    g, client = gateway([original, wrong_review, {'item_0': corrected.model_dump(mode='json')}, final_review])
    result = result_for([item().evidence[0].text])
    if valid_patch:
        assert ExecutiveBriefWriter(g).generate(result).items[0].text == corrected.text
    else:
        with pytest.raises(ValueError, match='direction'):
            ExecutiveBriefWriter(g).generate(result)
    audit = json.loads(next(w.message for w in result.validation_warnings if w.code == 'executive_brief_repair_audit'))
    assert audit['locked_indices'] == [] and 'Meaning review' in str(audit['initial_errors'])
    assert len(client.calls) == 4


def test_accounting_parentheses_and_long_summary_quotes_keep_signs_and_headers():
    result, _ = table_result()
    table = result.document.pages[0].tables[0]
    table.rows[0].cells = ['Net loss', '(1,250)', '(1,475)']
    source = '\n'.join(table.raw_header_lines) + '\n' + ('          \n' * 190) + 'Net loss (1,250) (1,475)'
    result.document.pages[0].text = source
    fact = SummaryFact(label='Loss', text='Net loss was (1,475) in 2024, in USD thousands.',
                       source_quote=source, source_pages=[1])
    assert len(source) > 1800
    assert not fact_errors(fact, result, source, 1)
    fact.text = 'Net loss was 1,475 in 2024, in USD thousands.'
    assert fact_errors(fact, result, source, 1)


def test_failed_meaning_review_retains_original_brief_in_audit():
    original = {'title': 'Shares', 'items': [item().model_dump(mode='json')]}
    g, client = gateway([original, {'items': []}])
    result = result_for([item().evidence[0].text])
    with pytest.raises(ValueError, match='every exact supplied index'):
        ExecutiveBriefWriter(g).generate(result)
    audit = json.loads(next(w.message for w in result.validation_warnings if w.code == 'executive_brief_repair_audit'))
    assert audit['original'] == original
    assert 'meaning_review' in audit['initial_errors']
    assert len(client.calls) == 2
