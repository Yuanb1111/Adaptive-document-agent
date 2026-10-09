"""Dated context must not discard a complete, source-bound scenario table."""
import pytest

from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.models import CompanyProfile, PresentationPlan
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.brief_context import _outcomes
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import gateway, payload, result_for


@pytest.mark.parametrize('period', [
    '12 months ended June 30, 2024', '6 months ended 2024-06-30',
    '2 years ended 31 December 2024',
])
def test_reporting_window_is_not_a_scenario_outcome(period):
    source = (f'Assuming demand matches the {period}, reserves could last '
              '18 months without expansion, 24 months with partial expansion '
              'or 36 months with full expansion.')
    result = result_for([source])
    data = payload('Reserve duration depends on expansion assumptions.', label='Capacity')
    data['items'][0]['evidence'][0]['text'] = source
    data['items'][0]['comparison_table'] = {
        'headers': ['Assumption', 'Estimated duration'],
        'rows': [['without expansion', '18 months'], ['with partial expansion', '24 months'],
                 ['with full expansion', '36 months']],
    }
    brief = ExecutiveBrief.model_validate(data)
    before = result.model_dump(), brief.model_dump()
    assert not validate_executive_brief(brief, result)
    assert (result.model_dump(), brief.model_dump()) == before
    brief.items[0].comparison_table.rows.pop(1)
    assert any('conditional outcome' in e for e in validate_executive_brief(brief, result))


def test_actual_durations_and_unknown_context_remain_checked():
    assert _outcomes('A buffer of 12 months is required with expansion.') == {'month': {'12'}}
    assert _outcomes('A minimum 12-month buffer is required.') == {'month': {'12'}}
    assert _outcomes('It lasts 12 months with demand unchanged.') == {'month': {'12'}}
    assert _outcomes('The 12 months ended badly.') == {'month': {'12'}}


def test_conditional_table_keeps_a_hyphenated_buffer_and_dated_assumption():
    source = ('Assuming demand matches the 12 months ended June 30, 2024, reserves last '
              '18 months without expansion or 24 months with expansion. '
              'With expansion, management requires a buffer of 12 months.')
    result = result_for([source])
    data = payload('These scenarios use historical demand and retain a 12-month buffer.', label='Reserves')
    data['items'][0]['evidence'][0]['text'] = source
    data['items'][0]['comparison_table'] = {
        'headers': ['Case', 'Duration'],
        'rows': [['without expansion', '18 months'], ['with expansion', '24 months']],
    }
    brief = ExecutiveBrief.model_validate(data)
    assert not validate_executive_brief(brief, result)
    brief.items[0].text = 'These scenarios use historical demand.'
    assert any('conditional outcome' in e for e in validate_executive_brief(brief, result))


def test_writer_supplies_literal_identity_without_displacing_selected_evidence():
    source = 'Field study participation was 82% in 2025.'
    texts = ['General background.'] * 11 + [source, 'Independent Research Centre.']
    result = result_for(texts)
    result.presentation_plan = PresentationPlan(title='Research review', company=CompanyProfile(
        name='Independent Research Centre', field_source_pages={'name': [13, 999]}))
    g, client = gateway([{'pages': [12]}, payload(source, page=12)])
    ExecutiveBriefWriter(g).generate(result)
    request = client.calls[1][1]['content']
    assert source in request and 'Independent Research Centre.' in request
    assert '"identity_source_pages": [13]' in request
    assert 'General background.' not in request
    assert len(client.calls) == 2
