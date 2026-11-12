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
    dict(page=9,text='@lines[1-2]'), dict(page=2,text='@lines[1]'),
    dict(page=99,text='@lines[1-2]'), dict(page=2,text='@lines[1-2] copied transcription')])
def test_wire_rejects_transcriptions_unknown_ranges_and_cross_page_reference_pairs(quote):
    _, schema, draft = source()
    draft['decisions'][0]['evidence'] = [quote]
    with pytest.raises(ValidationError):
        schema.model_validate(draft)


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


def test_oversized_single_line_remains_available_as_literal_substring():
    text = 'Literal source detail. ' * 120
    messages = [untrusted_document_message(json.dumps(dict(source_pages=numbered_source_pages([
        dict(page=7,text=text)]))))]
    schema = source_draft_schema(messages,SourceIntegrationDraft)
    proposal = schema(decisions=[dict(section_id='sample',disposition='omit',reason='Unapproved.',
                                     evidence=[dict(page=7,text='Literal source detail.')])])
    assert bind_source_quotes(proposal,{7:text})
