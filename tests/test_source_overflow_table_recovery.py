from copy import deepcopy
import json

import pytest
from adaptive_document_agent.agent.prompting import untrusted_document_message
from adaptive_document_agent.agent.source_integration_copy import revise_reopened_additions
from adaptive_document_agent.agent.source_integration_quotes import numbered_source_pages, bind_source_quotes
from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_budget_output_v145 import gateway, response


@pytest.mark.parametrize('case', ['complete', 'changed_evidence', 'half_word', 'foreign', 'nonadjacent_tail'])
def test_reopened_table_reuses_authorized_native_content_only(case):
    source = ('Except Mr. Liu himself, the team members are independent.\n'
              'Controls cover transactions. After the Listing, the Listing Rules apply.\n'
              'Annual confirmations are requested, including all relevant financial, operational and market information.')
    pages = {2: source}
    numbered = numbered_source_pages([dict(page=2, text=source)])
    refs = {o['preview']: o['ref'] for o in numbered[0]['table_cell_reference_options']}
    compound = '@phrase[2:0-23]'
    item = dict(label='Controls', text='The Listing Rules apply after Listing.',
                evidence=[dict(page=2, text='@lines[1-3]')])
    draft = SourceIntegrationDraft(additions=[item], decisions=[dict(section_id='controls', disposition='include',
        reason='Material conditions.', evidence=item['evidence'], brief_item_indexes=[6])])
    messages = [untrusted_document_message(json.dumps(dict(
        checks=[dict(section_id='controls', pages=[2])], source_pages=numbered)))]
    corrected = 'At meetings considering a proposed transaction, interested parties cannot vote.'
    authored = {**item, 'text': corrected + ' ' + 'Additional detail. ' * 30}
    short = 'Directors consider the measures sufficient.'
    table = dict(headers=['Condition', 'Obligation', 'Scope'], rows=[
        [compound, refs['the team members are independent.']],
        [refs['Controls cover transactions.'], refs['the Listing Rules apply.']],
        [refs['Annual confirmations are requested,'], refs['including all relevant financial,'],
         refs['operational and market information.']]])
    reply = {**deepcopy(item), 'text': short, 'comparison_table': table}
    if case == 'changed_evidence':
        reply['evidence'][0]['text'] = '@lines[1-1]'
    elif case == 'half_word':
        table['rows'][0][0] = '@phrase[2:0-21]'
    elif case == 'foreign':
        table['rows'][0][0] = '@phrase[3:0-23]'
    elif case == 'nonadjacent_tail':
        table['rows'][2][1] = refs['Controls cover transactions.']
    llm, client = gateway([response(json.dumps({'item_6': authored})), response(json.dumps({'item_6': reply}))])
    entry = {}
    if case == 'complete':
        repaired = revise_reopened_additions(llm, messages, draft, ['controls'], 6, entry)
        result = bind_source_quotes(repaired, pages)
        item = result.additions[0]
        assert item.text == corrected + ' ' + short
        assert item.comparison_table.headers == ['Condition', 'Obligation / Scope']
        assert item.comparison_table.rows == [
            ['Except Mr. Liu himself,', 'the team members are independent.'],
            ['Controls cover transactions.', 'After the Listing, the Listing Rules apply.'],
            ['Annual confirmations are requested,', 'including all relevant financial, operational and market information.']]
        assert item.evidence[0].text == source
        assert result.decisions[0].reason == draft.decisions[0].reason
        assert 'review' not in entry
    else:
        with pytest.raises(LLMStructuredOutputError):
            revise_reopened_additions(llm, messages, draft, ['controls'], 6, entry)
    assert len(client.requests) == 2
