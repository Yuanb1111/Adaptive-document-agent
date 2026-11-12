"""Restoring exact quantity IDs must not discard valid sibling corrections."""
from copy import deepcopy

import pytest
from pydantic import ConfigDict, ValidationError, create_model

from adaptive_document_agent.agent.brief_expanded_capacity import validate_expanded_patch
from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from tests.test_executive_brief import gateway,result_for


def test_expanded_reference_overflow_reaches_source_copy_correction_and_independent_review():
    source='Revenue was USD 12 million in 2025. The estimate remains conditional.'
    original=dict(title='Results',items=[dict(label='Revenue',text='Revenue was USD 99 million in 2025.',
        evidence=[dict(ref='p1_b1')])])
    patch=dict(item_0=dict(label='Revenue',text=['Revenue was ',dict(quantity_ref='q0'),
        ' in 2025. '+ 'The estimate remains conditional. '*20],evidence=[dict(ref='p1_b1')],
        quantity_representations=[]))
    corrected='Revenue was US$ 12 million in 2025. The estimate remains conditional.'
    llm,client=gateway([original,patch,dict(item_0=dict(text=corrected))])
    result=result_for([source])
    brief=ExecutiveBriefWriter(llm).generate(result)
    assert brief.items[0].text==corrected
    assert any(u['operation']=='BriefPatchCapacityCorrection' for u in llm.usage)
    assert any(u['operation']=='BriefMeaningReview' for u in llm.usage)
    import json
    audit=json.loads(next(w.message for w in result.validation_warnings if w.code=='executive_brief_repair_audit'))
    assert audit['outcome']=='repaired' and audit['expanded_quantity_copy_capacity']


def test_only_expanded_overflow_field_is_writable_and_successful_siblings_remain_exact():
    schema=create_model('Patch',__config__=ConfigDict(extra='forbid'),
        item_0=(ExecutiveBriefItem,...),item_1=(ExecutiveBriefItem,...))
    item=dict(label='Condition',text='Qualified source wording. '*30,
              evidence=[dict(page=1,text='The estimate remains conditional.')])
    expanded=dict(item_0=deepcopy(item),item_1={**deepcopy(item),'text':'A verified sibling.'})
    wire=deepcopy(expanded);wire['item_0']['text']=['Prose ',dict(quantity_ref='q0')]
    before=deepcopy(expanded),deepcopy(wire)
    class Model:
        calls=0
        def generate_structured(self,messages,model,**kwargs):
            self.calls+=1
            assert set(model.model_fields)=={'item_0'}
            assert set(model.model_fields['item_0'].annotation.model_fields)=={'text'}
            return model(item_0=dict(text='The estimate remains conditional.'))
    model,audit=Model(),{}
    patched=validate_expanded_patch(model,[],schema,wire,expanded,audit)
    assert model.calls==1 and patched.item_1.model_dump(exclude_none=True)==schema.model_validate({
        **expanded,'item_0':{**item,'text':'Valid copy.'}}).item_1.model_dump(exclude_none=True)
    assert (expanded,wire)==before
    assert patched.item_0.evidence[0].model_dump()==item['evidence'][0]


def test_literal_or_other_schema_failures_cannot_gain_a_reference_expansion_retry():
    schema=create_model('Patch',__config__=ConfigDict(extra='forbid'),item_0=(ExecutiveBriefItem,...))
    values=dict(item_0=dict(label='Finding',text='A'*551,evidence=[dict(page=1,text='Literal source.')]))
    class NoCalls:
        def generate_structured(self,*a,**k):pytest.fail('Not an expansion overflow')
    with pytest.raises(ValidationError):
        validate_expanded_patch(NoCalls(),[],schema,values,values,{})


def test_valid_partial_sibling_keeps_meaning_correction_without_reopening_malformed_source():
    import json
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    from tests.test_brief_item_repair import item,audited
    from tests.test_budget_output_v145 import gateway as model_gateway,response
    sources=['Revenue was 12.','Costs were 8.','Cash was 4.','Debt was 6.','Output was 20.']
    original=dict(title='Findings',items=[item(text,label=label) for text,label in
        zip(sources,['Revenue','Costs','Cash','Debt','Output'])])
    original['items'][3]['text']='Debt was 99.';original['items'][4]['text']='Output was 99.'
    bad=item(sources[3],label='Debt');bad['evidence'][0]['text']='An absent quotation. '*120
    patch=dict(item_3=bad,item_4=item(sources[4],label='Output'))
    target='The source reports output of 20.'
    llm,client=model_gateway([response(json.dumps(original)),response(json.dumps(patch)),
                             response(json.dumps(dict(item_3=dict(text=target))))])
    def review(brief):
        return {i:['Attribute the output to the source.'] for i,row in enumerate(brief.items)
                if row.label=='Output' and row.text!=target}
    result=result_for([' '.join(sources)])
    final=generate_with_item_repair(llm,[dict(role='system',content='Use the original untrusted source.')],
        result=result,excerpts={1:' '.join(sources)},topics=[],source_context={},semantic_validator=review)
    assert final.items[-1].text==target and len(client.requests)==3
    assert audited(result)['discarded_indices']==[3]
    assert not audited(result).get('post_source_correction')
