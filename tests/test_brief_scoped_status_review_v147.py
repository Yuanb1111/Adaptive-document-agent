"""Scoped status context cannot justify demanding a label for an unknown period."""
import json

import pytest

from adaptive_document_agent.agent.brief_audit_scope import audit_status_errors
from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
from adaptive_document_agent.models import TableRow
from adaptive_document_agent.models.executive_brief import BriefQuantityRepresentation
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_brief_audit_scope_v146 import _case


def scoped_flows():
    result, brief = _case()
    page, table = result.document.pages[0], result.document.pages[0].tables[0]
    table.rows[0].cells = ['Operating surplus', '1,250', '1,475']
    table.rows.append(TableRow(cells=['Investing outflow', '(100)', '(200)'], page=1,
                              alignment_status='resolved'))
    page.text = '\n'.join(table.raw_header_lines) + '\nOperating surplus 1,250 1,475\nInvesting outflow (100) (200)'
    item = brief.items[0]
    item.evidence[0].text = page.text
    item.text = ('Operating surplus rose from USD1,250 thousand in 6M2023 (unaudited) to '
                 'USD1,475 thousand in 6M2024. Investing outflow widened from USD100 thousand '
                 'in 6M2023 (unaudited) to USD200 thousand in 6M2024.')
    item.quantity_representations = [BriefQuantityRepresentation(
        quantity_text=f'USD{number} thousand', source_value=f'-{number}', representation='absolute_magnitude')
        for number in [100, 200]]
    return result, brief


class Reviewer:
    def __init__(self, *, accepted=True):
        self.calls = 0
        self.accepted = accepted

    def generate_structured(self, messages, schema, **kwargs):
        self.calls += 1
        if schema.__name__ == 'BriefClaimDirectionReview':
            from tests.brief_direction_fixture import accepted_directions
            return accepted_directions(messages, schema, self.verdict['items'])
        assert 'EXACT affected measure' in messages[0]['content']
        assert 'An unknown column cannot require' in messages[0]['content']
        row = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])[0]
        assert [(c['period'], c['status']) for c in row['source_audit_scope'][0]['columns']] == [
            ('6M2023', 'unaudited'), ('6M2024', 'unknown')]
        clauses = row['item']['text'].split('. ')
        response = schema(items=[dict(index=0, accepted=self.accepted,
            reason='The comparative status is present in each clause.' if self.accepted
                   else 'Investing outflow omits an unaudited qualification for 6M2024.',
            numeric_comparison=True, comparisons=[dict(claim=clause,
                start_value=start, end_value=end, direction='increase', absolute_magnitude=magnitude,
                start_ref='i0_q0', end_ref='i0_q0', start_duration_months=6, end_duration_months=6)
                for clause, start, end, magnitude in zip(clauses, ['1250', '-100'], ['1475', '-200'], [False, True])])])
        self.verdict = response.model_dump(mode='json')
        return response


def test_each_measure_preserves_only_its_supported_comparative_status_and_signed_magnitude():
    result, brief = scoped_flows()
    before = brief.model_dump_json()
    assert not validate_executive_brief(brief, result)
    assert not audit_status_errors(brief.items[0], result)
    reviewer = Reviewer()
    validate = meaning_validator(reviewer, result=result)
    assert validate(brief) == {}
    assert validate(brief) == {} and reviewer.calls == 2
    assert brief.model_dump_json() == before


def test_reviewer_rejection_stays_authoritative_and_unchanged_copy_uses_same_failed_memo():
    result, brief = scoped_flows()
    reviewer = Reviewer(accepted=False)
    validate = meaning_validator(reviewer, result=result)
    expected = {0: ['Investing outflow omits an unaudited qualification for 6M2024.']}
    assert validate(brief) == expected
    assert validate(brief.model_copy(deep=True)) == expected
    assert reviewer.calls == 1


@pytest.mark.parametrize('status', ['audited', 'unaudited'])
def test_accepted_review_cannot_supply_a_status_to_the_unknown_current_column(status):
    result, brief = scoped_flows()
    brief.items[0].text = brief.items[0].text.replace('to USD200 thousand in 6M2024',
                                                  f'to USD200 thousand in {status} 6M2024')
    errors = meaning_validator(Reviewer(), result=result)(brief)
    assert any('source column support' in error for error in errors[0])
