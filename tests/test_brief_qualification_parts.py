import json
from types import SimpleNamespace

import pytest
from pydantic import ConfigDict, ValidationError, create_model
from adaptive_document_agent.agent.brief_qualification_parts import (
    BODY_LIMIT, assemble_parts, part_item_model, qualification_parts, repack_oversized_compacts)


def inventory_parts():
    core = ('October 31, 2024 inventories were RMB 157903 thousand (unaudited). Turnover days were 395 '
            'for the six months ended June 30, 2024, mainly reflecting CR-series stock for overseas demand '
            'and seasonal low revenue recognition. By October 31, RMB 73.9 million of June inventory had '
            'been consumed or sold.')
    age = 'Inventory aged more than 1 year was 20% of gross inventory.'
    provision = 'At June 30, 2024, the inventory write-down provision was RMB 26.8 million, 15% of inventory costs.'
    proof1 = 'Over 1 year accounted for 20% of gross inventory. Over 2 years was less than 3%. Management monitored aged stock.'
    proof2 = 'The June provision was RMB26.8 million, representing 15% of inventory costs. Management believed the provision sufficient.'
    opts = {'p332_b14':dict(page=332,literal_proof=proof1,typed_quantities=[('', '20', '%')],
                             duration_thresholds=[('more than','1','year')]),
            'p332_b15':dict(page=332,literal_proof=proof2,typed_quantities=[('rmb','26.8','million'),('','15','%')],
                             duration_thresholds=[])}
    joined = dict(page=332,literal_proof=proof1+' '+proof2,typed_quantities=[('','20','%')],
                  duration_thresholds=[('more than','2','year')],percentage_thresholds=[('less than','3')])
    brief = SimpleNamespace(items=[SimpleNamespace(text=' '.join((core,age,provision)))])
    slots, options = qualification_parts(brief, dict(previous_options={0:opts}, quote_alias_options={0:{'i0_q0':joined}},
        previous_bindings={0:[dict(claim=age,source_ref='p332_b14'),dict(claim=provision,source_ref='p332_b15')]}))
    return core, slots[0], options[0]


def test_actual_oversized_continuation_composes_complete_variants_with_specific_sources():
    core, slots, options = inventory_parts()
    # The prior single-text protocol yielded 600 characters. These full parts
    # are taken from that paid reply, including its original date and units.
    finding = core.replace('mainly reflecting CR-series stock for overseas demand',
        'mainly due to CR-series stock for anticipated overseas demand')
    aging = ('At June 30, 2024, inventory aged over 1 year was 20 % of gross inventory; management monitored '
             'long-aged stock, and inventory aged over 2 years was less than 3%.')
    provision = ('At June 30, 2024, the write-down provision was RMB 26.8 million, 15 % of inventory costs; '
                 'management believed provision sufficient.')
    short_core = ('Inventories were RMB 157903 thousand at 2024-10-31 (unaudited). For the six months ended '
                  '2024-06-30, 395 turnover days reflected overseas stocking and seasonal revenue timing. '
                  'By October 31, RMB 73.9 million of June stock was sold or consumed.')
    short_aging = ('At 2024-06-30, 20% of gross inventory was over 1 year old and <3% was over 2 years. '
                   'Management monitored aged stock.')
    short_provision = ('At 2024-06-30, the RMB26.8 million provision was 15% of inventory costs. '
                       'Management considered it sufficient.')
    assert len(' '.join((finding,aging,provision))) == 600
    def variants(long, short):
        return dict(concise=dict(text=long), compact=dict(text=short))
    raw = dict(label='Inventory', finding=variants(finding,short_core),
               qualification_1=variants(aging,short_aging), qualification_2=variants(provision,short_provision))
    schema = part_item_model(0,slots)
    value = schema.model_validate(raw).model_dump()
    output = assemble_parts(value,slots,options)
    assert len(output['text']) <= BODY_LIMIT
    assert sum(s['compact_max_characters'] for s in slots.values()) + len(slots)-1 == BODY_LIMIT
    assert [b['source_ref'] for b in output['source_qualifications']] == ['p332_b14','p332_b15']
    assert all(b['claim'] in output['text'] for b in output['source_qualifications'])
    assert 'i0_q0' not in options
    assert output['text'] in [' '.join((x,y,z)) for x in (finding,short_core)
                             for y in (aging,short_aging) for z in (provision,short_provision)]
    # When a compact alternative exceeds only its allocation, pooled actual
    # measurements can still make a complete verified combination usable.
    raw['finding']['compact']['text'] = finding
    dynamic = create_model('ExecutiveBriefPatch', __config__=ConfigDict(extra='forbid'), item_0=(schema,...))
    with pytest.raises(ValidationError):
        dynamic.model_validate(dict(item_0=raw))
    pooled = repack_oversized_compacts(json.dumps(dict(item_0=raw)), dynamic, {0:slots}, {0:options}, [0])
    assert pooled is not None
    assert len(assemble_parts(pooled.item_0.model_dump(),slots,options)['text']) <= BODY_LIMIT
    raw['qualification_1']['concise']['source_ref'] = 'i0_q0'
    assert repack_oversized_compacts(json.dumps(dict(item_0=raw)), dynamic, {0:slots}, {0:options}, [0]) is None
