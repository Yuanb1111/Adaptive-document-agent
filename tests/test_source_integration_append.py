import json
from types import SimpleNamespace
import pytest

from adaptive_document_agent.agent.source_integration_append import (
    _source_cell, append_reviewed_findings, can_append_after_review,
)
from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft, SourceIntegrationVerdict
from adaptive_document_agent.agent.source_table_cells import phrase_cell_options
from tests.test_budget_output_v145 import gateway, response


@pytest.mark.parametrize('case', ['complete', 'foreign_item', 'foreign_evidence', 'missing_point', 'bad_row',
                                   'frozen_header', 'overlong', 'uncited_page', 'quote_is_not_coverage',
                                   'malformed_coverage', 'malformed_amendment', 'extra_root',
                                   'duplicate_amendment_key', 'duplicate_item', 'truncation'])
def test_incremental_source_tables_freeze_reviewed_copy_and_bind_new_material(case):
    pages = {1:'The earlier requirement is disclosed.', 2:(
        'When a Director or associate has a conflict in a proposed transaction,\n'
        'the interested Director abstains from the board vote and is excluded from quorum.\n'
        'Certain matters are referred to independent non-executive Directors for review.')}
    existing = dict(headers=['Trigger', 'Action'], rows=[['Earlier condition', 'Earlier consequence']])
    draft = SourceIntegrationDraft(additions=[
        dict(label='Locked',text='A reviewed finding.',evidence=[dict(page=1,text=pages[1])]),
        dict(label='Governance',text='The earlier requirement is disclosed.',
             evidence=[dict(page=1,text=pages[1])], comparison_table=existing)],
        decisions=[dict(section_id=sid, disposition='include', reason='Supported.',
                        evidence=[dict(page=1,text=pages[1])], brief_item_indexes=[i])
                   for i,sid in [(3,'accepted'),(4,'governance')]])
    previous = draft.model_copy(deep=True)
    previous.additions[1].comparison_table = None
    verdicts = {sid:SourceIntegrationVerdict(section_id=sid,accepted=approved,reason=reason)
                for sid,approved,reason in [('accepted',True,'Covered.'),('governance',False,
                    'Keep the earlier requirement; include the board vote and quorum. Add the independent review.')]}
    earlier = {**verdicts,'governance':verdicts['governance'].model_copy(update={'reason':'Correct the scope.'})}
    assert can_append_after_review((previous,earlier),draft,verdicts,{'governance'},3)
    assert not can_append_after_review((previous,verdicts),draft,verdicts,{'governance'},3)
    assert not can_append_after_review((draft,earlier),draft,verdicts,{'governance'},3)
    refs = [o['ref'] for o in phrase_cell_options(2,pages[2])]
    amendment = dict(item='item_4', append_text='Certain matters go to independent non-executive Directors for review.',
        append_rows=[refs[:2]], evidence=[dict(page=2,text='@lines[1-3]')])
    coverage = [dict(objection=f'issue_{i}',item='item_4',visible_text=v) for i,v in enumerate(
        ['earlier requirement', 'new_row_1','new_text'],1)]
    if case == 'foreign_item':
        amendment['item'] = 'item_3'
    elif case == 'foreign_evidence':
        amendment['evidence'][0]['page'] = 99
    elif case == 'missing_point':
        coverage.pop()
    elif case == 'bad_row':
        amendment['append_rows'][0].pop()
    elif case == 'frozen_header':
        amendment['table_headers'] = ['Foreign','Header']
    elif case == 'overlong':
        amendment['append_text'] = 'X'*545
    elif case == 'uncited_page':
        amendment['evidence'] = []
    elif case == 'quote_is_not_coverage':
        coverage[1]['visible_text'] = 'This sentence is not displayed.'
    elif case in {'malformed_coverage','malformed_amendment'}:
        # Actual #09 returned a complete edits array and then a malformed
        # author's map with an extra JSON property in its sole entry.
        coverage = [{**coverage[0], '},{':' '}]
        if case == 'malformed_amendment':
            amendment['unexpected'] = 'Changed a locked property.'
    raw = dict(amendments=[amendment], coverage=coverage)
    if case == 'extra_root':
        raw['foreign'] = {}
    if case == 'duplicate_item':
        raw['amendments'].append(amendment)
    wire = json.dumps(raw)
    if case == 'duplicate_amendment_key':
        wire = wire.replace('"append_text":', '"append_text": "arbitrary earlier value", "append_text":', 1)
    if case == 'truncation':
        wire = wire[:-5]
    llm, client = gateway([response(wire, finish='content_filter' if case == 'truncation' else 'stop')])
    saved = draft.model_dump()
    args = (llm,draft,verdicts,['governance'],3,{'governance':SimpleNamespace(pages=[1,2],decision_impact='Test')},pages,{})
    if case in {'complete','missing_point','quote_is_not_coverage','malformed_coverage'}:
        result = append_reviewed_findings(*args)
        assert result.decisions == draft.decisions and result.additions[0] == draft.additions[0]
        original, revised = draft.additions[1],result.additions[1]
        assert revised.text == original.text + ' ' + amendment['append_text']
        assert revised.comparison_table.rows == [*original.comparison_table.rows,pages[2].splitlines()[:2]]
        assert revised.evidence[:-1] == original.evidence and revised.evidence[-1].text == pages[2]
        status = args[-1]['append_writer_coverage']['status']
        assert status == ('references_located' if case == 'complete' else 'invalid')
        assert 'review' not in args[-1]
    else:
        from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
        with pytest.raises((ValueError,LLMStructuredOutputError)):
            append_reviewed_findings(*args)
    assert draft.model_dump() == saved
    assert len(client.requests) == 1


def test_compound_source_cell_joins_all_ordered_offered_terms_only_inside_one_literal():
    raw = 'We have sufficient capital, facilities, equipment and employees to operate independently.'
    options = phrase_cell_options(274,raw)
    owned = {o['ref']:274 for o in options}
    refs = list(owned)
    assert len(refs) == 3
    assert _source_cell(' '.join(refs), {274}, {274:raw}, owned) == f'@phrase[274:0-{len(raw)}]'
    for invalid in ([refs[0],refs[2]], list(reversed(refs)), [refs[0],refs[0]], [refs[0],'@phrase[274:8-20]']):
        with pytest.raises(ValueError):
            _source_cell(' '.join(invalid), {274}, {274:raw}, owned)
