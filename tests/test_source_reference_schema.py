"""Page/reference pairs are validated before any model proposal reaches review."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.prompting import untrusted_document_message
from adaptive_document_agent.agent.source_reference_schema import source_draft_schema
from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
from adaptive_document_agent.agent.source_integration_quotes import numbered_source_pages, bind_source_quotes


def source():
    pages = {2: 'A literal source qualification.\nA separate limitation.',
             9: 'An independently scoped source finding.'}
    messages = [untrusted_document_message(json.dumps(dict(source_pages=numbered_source_pages(
        [dict(page=n, text=t) for n, t in pages.items()]))))]
    schema = source_draft_schema(messages, SourceIntegrationDraft)
    draft = dict(decisions=[dict(section_id='sample', disposition='omit',
        reason='Unapproved test proposal.', evidence=[dict(page=2, text='@lines[1-2]')])])
    return pages, schema, draft


def test_wire_reference_restores_original_text_without_mutating_source_or_proposal():
    pages, schema, draft = source()
    proposal = schema.model_validate(draft)
    before = deepcopy(pages), proposal.model_dump()
    bound = bind_source_quotes(proposal, pages)
    assert bound.decisions[0].evidence[0].text == pages[2]
    assert (pages, proposal.model_dump()) == before
    assert bound.decisions[0].model_dump(exclude={'evidence'}) == proposal.decisions[0].model_dump(exclude={'evidence'})


@pytest.mark.parametrize('quote', [dict(page=2,text='A literal source qualification.'),
    dict(page=9,text='@lines[1-2]'), dict(page=2,text='@lines[3]'),
    dict(page=99,text='@lines[1-2]'), dict(page=2,text='@lines[1-2] copied transcription')])
def test_wire_rejects_transcriptions_unknown_ranges_and_cross_page_reference_pairs(quote):
    _, schema, draft = source()
    draft['decisions'][0]['evidence'] = [quote]
    with pytest.raises(ValidationError):
        schema.model_validate(draft)


def test_wire_resolves_a_valid_explicit_range_outside_the_suggested_chunks():
    pages, schema, draft = source()
    draft['decisions'][0]['evidence'] = [dict(page=2, text='@lines[1]')]
    bound = bind_source_quotes(schema.model_validate(draft), pages)
    assert bound.decisions[0].evidence[0].text == pages[2].splitlines()[0]


def test_full_scoped_brief_repairs_overlong_body_into_owned_table():
    from adaptive_document_agent.agent.source_integration_copy import revise_reopened_additions
    from tests.test_budget_output_v145 import gateway, response

    text = 'Notice is required.\nCancellation follows nonpayment.'
    pages = {2: text}
    numbered = numbered_source_pages([dict(page=2, text=text)])
    messages = [untrusted_document_message(json.dumps(dict(
        checks=[dict(section_id='contracts', pages=[2])], source_pages=numbered)))]
    item = dict(label='Cancellation', text='Cancellation has specified conditions.',
                evidence=[dict(page=2, text='@lines[1-2]')])
    draft = SourceIntegrationDraft(additions=[item], decisions=[dict(
        section_id='contracts', disposition='include', reason='Material conditions.',
        evidence=item['evidence'], brief_item_indexes=[6])])
    refs = [entry['ref'] for entry in numbered[0]['table_cell_reference_options']]
    table = dict(headers=['Notice', 'Consequence'], rows=[refs])
    llm, _ = gateway([response(json.dumps({'item_6': {**item, 'text': 'A' * 690}})),
                       response(json.dumps({'item_6': {'text': item['text'], 'comparison_table': table}}))])
    entry = {}
    repaired = revise_reopened_additions(llm, messages, draft, ['contracts'], 6, entry)
    bound = bind_source_quotes(repaired, pages)
    assert bound.additions[0].comparison_table.rows == [text.splitlines()]
    assert bound.additions[0].evidence[0].text == text
    assert repaired.decisions == draft.decisions
    assert [row['operation'] for row in llm.usage] == ['ReopenedSourceAdditions', 'ReopenedSourceOverflowTable']
    assert 'review' not in entry


def test_no_reference_directory_preserves_legacy_literal_transport():
    schema = source_draft_schema([], SourceIntegrationDraft)
    proposal = schema(decisions=[dict(section_id='sample',disposition='omit',reason='Unapproved.',
                                     evidence=[dict(page=2,text='A literal source qualification.')])])
    assert bind_source_quotes(proposal,{2:'A literal source qualification.'})


def test_wire_addition_restores_literal_comparison_cells_and_evidence_together():
    pages, schema, draft = source()
    from adaptive_document_agent.agent.source_table_cells import phrase_cell_options
    options = phrase_cell_options(2, pages[2])
    draft['additions'] = [dict(label='Source qualification', text='An unapproved source summary.',
        evidence=[dict(page=2,text='@lines[1-2]')], comparison_table=dict(headers=['Condition','Limit'],
        rows=[[options[0]['ref'],options[1]['ref']]]))]
    proposal = schema.model_validate(draft)
    bound = bind_source_quotes(proposal,pages)
    assert bound.additions[0].comparison_table.rows == [[o['text'] for o in options]]
    assert bound.additions[0].evidence[0].text == pages[2]
    assert proposal.additions[0].comparison_table.rows[0][0].startswith('@phrase[')


def test_writer_and_targeted_retry_keep_one_predicate_across_adjacent_offered_clauses():
    from adaptive_document_agent.agent.source_integration_copy import revise_reopened_additions
    from tests.test_budget_output_v145 import gateway, response

    subject = 'For the compact model,'
    predicate = ('the unit cannot detect motion, connect to external devices, '
                 'or be adjusted except through a workstation.')
    page = subject + ' ' + predicate + '\r\nOther models have a different interface.'
    pages = {3: page}
    first = len(subject) + 1
    cell = f'@phrase[3:{first}-{first + len(predicate)}]'
    numbered = numbered_source_pages([dict(page=3, text=page)])
    options = numbered[0]['table_cell_reference_options']
    assert cell not in {o['ref'] for o in options}
    messages = [untrusted_document_message(json.dumps(dict(
        checks=[dict(section_id='interfaces', pages=[3])], source_pages=numbered)))]
    item = dict(label='Product limits', text='The compact model has interface restrictions.',
                evidence=[dict(page=3, text='@lines[1]')])
    table = dict(headers=['Model', 'Restrictions'], rows=[[options[0]['ref'], cell]])
    decision = dict(section_id='interfaces', disposition='include', reason='Material product differences.',
                    brief_item_indexes=[2], evidence=item['evidence'])
    schema = source_draft_schema(messages, SourceIntegrationDraft)
    draft = schema.model_validate(dict(decisions=[decision], additions=[{**item, 'comparison_table': table}]))
    assert bind_source_quotes(draft, pages).additions[0].comparison_table.rows == [[subject, predicate]]

    # A complete authored patch takes the identical source-bound path without spending a format call.
    earlier = SourceIntegrationDraft(decisions=[decision], additions=[item])
    llm, client = gateway([response(json.dumps({'item_2': {**item, 'comparison_table': table}}))])
    repaired = revise_reopened_additions(llm, messages, earlier, ['interfaces'], 2, {})
    assert bind_source_quotes(repaired, pages).additions[0].comparison_table.rows == [[subject, predicate]]
    assert len(client.requests) == 1

    for invalid in (f'@phrase[3:{first + 1}-{first + len(predicate)}]',
                    f'@phrase[3:{first}-{len(page)}]', cell.replace('[3:', '[4:')):
        with pytest.raises(ValidationError):
            schema.model_validate(dict(decisions=[decision], additions=[{**item, 'comparison_table':
                {**table, 'rows': [[options[0]['ref'], invalid]]}}]))
    uncovered = draft.model_dump(mode='json')
    uncovered['additions'][0]['evidence'] = [dict(page=3, text='@lines[2]')]
    with pytest.raises(ValueError, match='own quoted evidence'):
        bind_source_quotes(schema.model_validate(uncovered), pages)


def test_oversized_single_line_remains_available_as_literal_substring():
    text = 'Literal source detail. ' * 120
    messages = [untrusted_document_message(json.dumps(dict(source_pages=numbered_source_pages([
        dict(page=7,text=text)]))))]
    schema = source_draft_schema(messages,SourceIntegrationDraft)
    proposal = schema(decisions=[dict(section_id='sample',disposition='omit',reason='Unapproved.',
                                     evidence=[dict(page=7,text='Literal source detail.')])])
    assert bind_source_quotes(proposal,{7:text})


def test_reopened_addition_can_cite_measured_ranges_and_create_a_literal_table():
    from adaptive_document_agent.agent.source_integration_copy import revise_reopened_additions

    pages = {2: 'Notice is required.\nCancellation follows nonpayment.',
             9: 'Renewals require written consent.'}
    numbered = numbered_source_pages([dict(page=n, text=t) for n, t in pages.items()])
    messages = [untrusted_document_message(json.dumps(dict(
        checks=[dict(section_id='contracts', pages=[2, 9])], source_pages=numbered)))]
    item = dict(label='Cancellation', text='Notice is required.',
                evidence=[dict(page=2, text='Notice is required.')])
    previous = SourceIntegrationDraft(additions=[item], decisions=[dict(
        section_id='contracts', disposition='include', reason='Material condition.',
        evidence=item['evidence'], brief_item_indexes=[3])])
    saved = previous.model_dump()

    class Gateway:
        def generate_structured(self, request, schema, **kwargs):
            assert 'may create a comparison_table' in request[-1]['content']
            assert 'Notice is required.' not in json.dumps(schema.model_json_schema())
            assert schema(item_3=item).item_3.evidence[0].text == item['evidence'][0]['text']
            for quote in (dict(page=9, text='Notice is required.'),
                          dict(page=2, text='Cancellation follows nonpayment.'),
                          dict(page=9, text='@lines[1-2]')):
                with pytest.raises(ValidationError):
                    schema(item_3={**item, 'evidence': [quote]})
            refs = [cell['ref'] for cell in numbered[0]['table_cell_reference_options']]
            return schema(item_3={**item, 'evidence': [dict(page=2, text='@lines[1-2]')],
                'comparison_table': dict(headers=['Notice', 'Consequence'], rows=[refs])})

    entry = {}
    revised = revise_reopened_additions(Gateway(), messages, previous, ['contracts'], 3, entry)
    bound = bind_source_quotes(revised, pages)
    assert bound.additions[0].evidence[0].text == pages[2]
    assert bound.additions[0].comparison_table.rows == [pages[2].splitlines()]
    assert entry['edited_addition_indexes'] == [3]
    assert previous.model_dump() == saved


@pytest.mark.parametrize('case', ['recover', 'unknown_page', 'extra', 'nonscalar', 'bad_repair', 'refusal'])
def test_only_known_page_reference_text_gets_one_targeted_repair(case):
    from adaptive_document_agent.agent.source_integration_copy import revise_reopened_additions
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    from tests.test_budget_output_v145 import gateway, response

    pages = {2: 'Notice is required.\nCancellation follows nonpayment.',
             9: 'Renewals require written consent.'}
    numbered = numbered_source_pages([dict(page=n, text=t) for n, t in pages.items()])
    messages = [untrusted_document_message(json.dumps(dict(
        checks=[dict(section_id='contracts', pages=[2, 9])], source_pages=numbered)))]
    items = [dict(label='Cancellation', text='Notice is required.',
                  evidence=[dict(page=2, text='Notice is required.')]),
             dict(label='Renewals', text=pages[9], evidence=[dict(page=9, text=pages[9])])]
    previous = SourceIntegrationDraft(additions=items, decisions=[dict(
        section_id='contracts', disposition='include', reason='Material conditions.',
        evidence=items[0]['evidence'], brief_item_indexes=[3, 4])])
    quote = dict(page=2, text='An unapproved transcription.')
    if case == 'unknown_page':
        quote['page'] = 77
    if case == 'extra':
        quote['forged'] = 'unrelated parameter'
    if case == 'nonscalar':
        quote['text'] = ['invalid']
    first = dict(item_3={**items[0], 'evidence': [quote]}, item_4=items[1])
    ref = '@lines[99-99]' if case == 'bad_repair' else '@lines[1-2]'
    correction = dict(item_3=dict(evidence=[dict(page=2, text=ref)]))
    llm, client = gateway([response(json.dumps(first), finish='content_filter' if case == 'refusal' else 'stop'),
                           response(json.dumps(correction))])
    entry = {}
    if case == 'recover':
        revised = revise_reopened_additions(llm, messages, previous, ['contracts'], 3, entry)
        assert entry['format_locked_keys'] == ['item_4']
        assert revised.additions[1] == previous.additions[1]
        assert revised.additions[0].text == items[0]['text']
        assert bind_source_quotes(revised, pages).additions[0].evidence[0].text == pages[2]
    else:
        with pytest.raises(LLMStructuredOutputError):
            revise_reopened_additions(llm, messages, previous, ['contracts'], 3, entry)
    assert len(client.requests) == (2 if case in {'recover', 'bad_repair'} else 1)
