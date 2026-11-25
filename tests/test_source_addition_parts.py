from copy import deepcopy
import json
import pytest
from adaptive_document_agent.agent.source_addition_parts import assemble_source_parts, part_context
from adaptive_document_agent.agent.source_addition_span_edits import SourceSpanEdit, _apply_edits
from adaptive_document_agent.agent.source_integration_copy import shorten_additions
from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
from tests.test_budget_output_v145 import gateway, response


TECH = ('2025–2029 development estimates may change with actual needs and market conditions. '
    'Encoder hardware and motors target external testing and certification and small-batch production in 2027, '
    'then mass production in 2028; embodied AI targets prototype verification and testing before 2028 mass '
    'production; process toolkits target mass deployment in 2028. Estimated costs: HK$48.7 million for '
    'proprietary key components and HK$226.3 million for embodied AI. These are plans, not completed '
    'capabilities; the pages do not state growth or commercialization depends on completion.')
GOVERNANCE = ('Safeguards exclude controlling shareholders with a material interest from voting and quorum '
    'at relevant shareholders’ meetings; include connected-transaction controls and Listing Rules compliance '
    'after Listing; provide independent professional advice at company expense when Directors reasonably '
    'request it; and include committees, annual non-competing-interest confirmations with requested '
    'information, and disclosure of independent directors’ reviewed decisions, if any. Directors consider '
    'the measures sufficient. The pages describe controls, not transaction-level details.')


def test_identical_overflowing_versions_get_one_scoped_repair_with_every_source_binding_preserved():
    quotes=[dict(page=3,text='Literal original source passage.')]
    records=[dict(label=f'Finding {i}',text=text,evidence=deepcopy(quotes)) for i,text in enumerate((
        TECH, 'Ownership remains as stated.', 'The company qualifies its independence assessment.', GOVERNANCE))]
    draft=dict(additions=records, decisions=[dict(section_id='a',disposition='include',reason='Covered.',
        brief_item_indexes=[3,4,5,6],evidence=deepcopy(quotes))])
    original=deepcopy(draft)
    errors=[dict(loc=['additions',i,'text'],ctx=dict(max_length=550)) for i in (0,3)]
    over={f'addition_{i}_text':dict(complete=records[i]['text'],concise=records[i]['text']) for i in (0,3)}
    answers=dict(addition_0_text=dict(
        part_1='Encoder hardware and motors target external tests, certification and small batches in 2027, then mass production in 2028',
        part_2='embodied AI targets prototype checks and tests before 2028 mass production',
        part_3='toolkits target mass deployment in 2028'),
        addition_3_text=dict(part_1='Materially interested controlling shareholders cannot vote or count toward quorum at relevant shareholder meetings',
        part_2='connected transactions face controls and Listing Rules after Listing',
        part_3='Directors may reasonably request independent professional advice at company expense',
        part_4='and committees, annual non-compete confirmations, requested information and disclosure of independent directors’ reviewed decisions, if any'))
    llm,_=gateway([response(json.dumps(over)),response(json.dumps(answers))])
    audit={}
    repaired=shorten_additions(llm,[],SourceIntegrationDraft,(draft,errors),audit,3,sentence_compress=True)
    assert len(llm.usage)==2
    assert set(audit['source_part_targets']) == set(over)
    assert [i.model_dump() for i in repaired.decisions]==original['decisions']
    assert all(i.evidence[0].model_dump()==quotes[0] for i in repaired.additions)
    assert [i.text for i in repaired.additions[1:3]]==[r['text'] for r in original['additions'][1:3]]
    for i in (0,3):
        target=part_context([original['additions'][i]['text']],550)
        assert repaired.additions[i].text.startswith(target['prefix']) and repaired.additions[i].text.endswith(target['suffix'])
        assert len(repaired.additions[i].text)<=550
        assert target['maximum']==sum(c['max_characters'] for c in target['parts'].values())+len(
            target['prefix']+target['suffix']+''.join(target['separators']))
    wrong=deepcopy(answers)
    wrong['addition_0_text']['part_1']=wrong['addition_0_text']['part_1'].replace('2027','2026')
    with pytest.raises(ValueError,match='exact source quantities'):
        assemble_source_parts(wrong,{'addition_0_text':part_context([TECH],550)})


def test_paid_sixth_parts_lock_technology_and_request_only_governance_phrase_edits():
    # Complete paid reply. It overshot both pooled findings despite making progress.
    parts = dict(addition_0_text=dict(
        part_1='Encoder hardware and motors target external testing/certification and 2027 small-batch production, then 2028 mass production',
        part_2='embodied AI targets prototype verification/testing before 2028 mass production',
        part_3='process toolkits target 2028 mass rollout'),
        addition_3_text=dict(
        part_1='Safeguards exclude materially interested controlling shareholders from voting and quorum at relevant shareholders’ meetings',
        part_2='include connected-transaction controls and Listing Rules compliance after Listing',
        part_3='provide independent professional advice, company-funded on Directors’ reasonable request',
        part_4='include committees, annual non-competing-interest confirmations with requested information, and disclose independent directors’ reviewed decisions, if any'))
    tech_version = TECH.replace('Estimated costs:', 'Estimated costs are').replace('not state', 'not say')
    alternatives = dict(addition_0_text=dict(complete=tech_version, concise=tech_version),
                        addition_3_text=dict(complete=GOVERNANCE, concise=GOVERNANCE))
    edits = dict(addition_3_text=[dict(before='with requested information', after='with requested details'),
        dict(before='independent directors’ reviewed decisions, if any', after='any decisions independent directors reviewed')])
    texts = [TECH, 'Control is reported.', 'Directors give their view.', GOVERNANCE]
    records = [dict(label=f'Finding {i}', text=text, evidence=[dict(page=i+1,text='Owned evidence.')])
               for i, text in enumerate(texts)]
    decisions = [dict(section_id='a', disposition='include', reason='Covered.', brief_item_indexes=[3,4,5,6],
                      evidence=[dict(page=1,text='Owned evidence.')])]
    errors = [dict(loc=['additions', i, 'text'], ctx=dict(max_length=550)) for i in (0,3)]
    llm, client = gateway([response(json.dumps(value)) for value in (alternatives, parts, edits)])
    audit = {}
    result = shorten_additions(llm, [], SourceIntegrationDraft,
        (dict(additions=deepcopy(records),decisions=decisions),errors), audit, 3, sentence_compress=True)
    assert len(client.requests) == 3
    packet = next(m['content'] for m in client.requests[-1][0]
                  if m['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>'))
    micro_request = json.loads(packet.split('\n')[1])['source_addition_span_edits']
    assert set(micro_request) == {'addition_3_text'}
    assert micro_request['addition_3_text']['clause'] == parts['addition_3_text']['part_4']
    assert micro_request['addition_3_text']['minimum_saving'] == 7
    assert micro_request['addition_3_text']['locked_evidence'] == records[3]['evidence']
    assert [len(result.additions[i].text) for i in (0,3)] == [537,548]
    assert [item.text for item in result.additions[1:3]] == texts[1:3]
    assert 'HK$48.7m' in result.additions[0].text and 'HK$226.3m' in result.additions[0].text
    assert result.additions[0].text.endswith('do not say growth or commercialization depends on completion.')
    assert [v.model_dump() for v in result.decisions] == decisions
    assert [v.evidence[0].model_dump() for v in result.additions] == [v['evidence'][0] for v in records]


@pytest.mark.parametrize('before,after', [
    ('annual costs of HK$20 million', 'HK$20bn'), ('annual costs of HK$20 million', 'US$20m'),
    ('costs outside this clause', 'costs'), ('nnual costs', 'costs'),
    ('reviewed decisions','decisions')])
def test_phrase_repair_rejects_foreign_partial_ambiguous_or_changed_quantities(before,after):
    body = 'Directors reviewed decisions, reviewed decisions and annual costs of HK$20 million.'
    with pytest.raises(ValueError, match='No set of exact'):
        _apply_edits(body, dict(offset=0,clause=body),
                     [SourceSpanEdit(before=before,after=after)],len(body)-1)
