import pytest

from adaptive_document_agent.agent.brief_semantic_repair import correct_new_meaning_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from tests.test_executive_brief import result_for, payload


@pytest.mark.parametrize('change', ['accepted', 'wrong_unit', 'wrong_threshold', 'wrong_ref',
                                    'unrequested_value', 'other_clause', 'review_rejects'])
def test_reviewer_requested_aging_and_provision_require_exact_proof_and_fresh_review(change):
    original = 'The company reported inventories.'
    blocks = dict(p1_b13='The company monitors working capital.',
        p1_b14='Inventories aged more than 1 year accounted for 20% of gross inventories. Other assets represented 30%.',
        p1_b15='The inventory provision was RMB26.8 million, representing 15% of inventory costs.')
    text = '\n'.join([original, *blocks.values()])
    result = result_for([text])
    brief = ExecutiveBrief.model_validate(payload(original))
    brief.items[0].evidence[0].text = original
    issue = ('p1_b13–p1_b15: Include aging over one year at 20% of gross inventories '
             'and the inventory provision of RMB26.8 million (15%).')
    aging = 'Inventories aged over one year accounted for 20% of gross inventories.'
    provision = 'The provision was RMB26.8 million, or 15% of inventory costs.'
    if change == 'wrong_unit':
        provision = provision.replace('million', 'billion')
    if change == 'wrong_threshold':
        aging = aging.replace('over one year', 'under one year')
    if change == 'unrequested_value':
        aging += ' Other assets represented 30%.'
    supplied = ' '.join((original, aging, provision))
    if change == 'other_clause':
        supplied += ' There was one subsidiary.'
    reviewed = []
    def review(candidate):
        reviewed.append(candidate)
        return {0: [issue]} if candidate.items[0].text == original or change == 'review_rejects' else {}
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            return schema(item_0=dict(text=supplied, source_qualifications=[
                dict(claim=aging, source_ref='p1_b15' if change=='wrong_ref' else 'p1_b14'),
                dict(claim=provision, source_ref='p1_b15')]))
    audit = {}
    candidate = correct_new_meaning_errors(Client(), brief, result=result, excerpts={1:text},
        topics=[], source_context={}, evidence_catalog={k:dict(page=1,text=v) for k,v in blocks.items()},
        semantic_validator=review, audit=audit)
    record = audit['post_source_meaning_correction']
    assert record['added_source_refs'] == {0:list(blocks)}
    assert (candidate is not None) == (change=='accepted')
    assert len(reviewed) == (2 if change in {'accepted', 'review_rejects'} else 1)
    if candidate:
        assert reviewed[-1] == candidate and candidate.items[0].text == supplied
        assert [q.text for q in candidate.items[0].evidence] == [original, *blocks.values()]


@pytest.mark.parametrize('outcome', ['accepted', 'symbol', 'wrong_alias', 'exact_rate', 'inclusive_limit', 'review_rejects'])
def test_further_source_counterevidence_uses_latest_reviewed_item_and_its_joined_quote_alias(outcome):
    original = 'Inventory was reported at June 30, 2024.'
    evidence = [
        'The company monitors working capital.',
        'At June 30, 2024, inventories over 1 year represented 20% of gross inventories. '
        'The proportion over 2 years was less than 3%, and management monitored aged stock.',
        'The provision was RMB26.8 million or 15% of costs. Management believed the provision was sufficient.']
    # Same page with a separate original item passage makes i0_q1 a joined
    # three-block passage, never the second primitive quote.
    page = original + ' Intervening material on the page. ' + ' '.join(evidence)
    result = result_for([page])
    brief = ExecutiveBrief.model_validate(payload(original))
    brief.items[0].evidence[0].text = original
    prior = 'Inventories over one year were 20% of gross inventories.'
    dated = 'At June 30, 2024, inventories over one year were 20% of gross inventories.'
    provision = 'The provision was RMB26.8 million or 15% of costs.'
    counter = 'Less than 3% of inventory was over two years old.'
    if outcome == 'symbol':
        counter = '<3% of inventory was >2 years old.'
    if outcome == 'exact_rate':
        counter = 'The share of inventory over two years old was 3%.'
    if outcome == 'inclusive_limit':
        counter = 'At most 3% of inventory was over two years old.'
    balanced = 'Management monitored aged stock and considered the provision sufficient.'
    initial_error = 'p1_b13–p1_b15: Add the over one year category at 20% and RMB26.8 million provision (15%).'
    next_errors = ['The 20% share needs its June 30, 2024 period.',
        'i0_q1: Inventory over two years was less than 3%; management monitored aged stock and believed the provision sufficient.']
    calls, reviewed = [], []
    def review(candidate):
        text = candidate.items[0].text
        reviewed.append(text)
        if text == original:
            return {0:[initial_error]}
        if counter not in text or outcome == 'review_rejects':
            return {0:next_errors}
        return {}
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(messages)
            if len(calls)==1:
                return schema(item_0=dict(text=' '.join((original, prior, provision)), source_qualifications=[
                    dict(claim=prior, source_ref='p1_b14'), dict(claim=provision, source_ref='p1_b15')]))
            assert 'reviewed_qualification_continuation' in str(messages)
            assert len(calls) <= 3
            def variants(text):
                return dict(concise=dict(text=text), compact=dict(text=text))
            aging_part = dated + ' ' + counter
            provision_part = provision + ' ' + balanced
            if outcome == 'wrong_alias':
                aging_part, provision_part = provision_part, aging_part
            return schema(item_0=dict(finding=variants(original), qualification_1=variants(aging_part),
                qualification_2=variants(provision_part)))
    audit = {}
    def run():
        return correct_new_meaning_errors(Client(), brief, result=result, excerpts={1:page}, topics=[],
            source_context={}, evidence_catalog={f'p1_b{i}':dict(page=1,text=v) for i,v in enumerate(evidence,13)},
            semantic_validator=review, audit=audit)
    if outcome in {'wrong_alias', 'exact_rate', 'inclusive_limit'}:
        with pytest.raises(ValueError, match='binds its quantities'):
            run()
        candidate = None
    else:
        candidate = run()
    assert len(calls) == (3 if outcome in {'wrong_alias', 'exact_rate', 'inclusive_limit'} else 2)
    assert (candidate is not None) == (outcome in {'accepted', 'symbol'})
    assert len(reviewed) == (3 if outcome in {'accepted', 'symbol', 'review_rejects'} else 2)
    followup = audit['post_source_meaning_correction']['reviewed_qualification_continuation']['post_source_meaning_correction']
    assert followup['joined_review_sources'][0]['i0_q1']['literal_proof'] == ' '.join(evidence)
    assert set(followup['reviewed_qualification_options'][0]) == {'p1_b14','p1_b15'}
    if candidate:
        assert reviewed[-1] == candidate.items[0].text
