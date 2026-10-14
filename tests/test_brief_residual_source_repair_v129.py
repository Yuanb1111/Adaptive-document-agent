import pytest
from adaptive_document_agent.agent.brief_source_repair import correct_residual_source_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for, payload


@pytest.mark.parametrize('valid', [True, False])
def test_residual_source_correction_freezes_valid_findings_and_rechecks_every_claim(valid):
    source = 'Revenue was USD 12 million in 2024. Expenses were USD -7 million in 2024.'
    result = result_for([source])
    original = ExecutiveBrief.model_validate(payload('Revenue was USD 99 million in 2024.'))
    original.items[0].evidence[0].text = source
    expense = original.items[0].model_copy(update={'label':'Expenses','text':'Expenses were USD 9 million in 2024.'})
    original.items.append(expense)
    errors = {f'item_{i}':validate_executive_brief(ExecutiveBrief(title='Source',items=[item]),
        result, excerpts={1:source}) for i,item in enumerate(original.items)}
    current = original.model_copy(deep=True)
    current.items[0].text = 'Revenue was USD 12 million in 2024.'
    current.items[1].text = 'Expenses were USD 7 million in 2024.'
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert set(schema.model_fields) == {'item_1'}
            return schema(item_1={'text':'Expenses were USD ' + ('-7' if valid else '7') + ' million in 2024.'})
    client, audit = Client(), {}
    corrected = correct_residual_source_errors(client, current, result=result, excerpts={1:source},
        initial_errors=errors, audit=audit)
    assert client.calls == 1
    if valid:
        assert corrected.items[0] == current.items[0]
        assert corrected.items[1].evidence == current.items[1].evidence
        assert not validate_executive_brief(corrected, result, excerpts={1:source})
    else: assert corrected is None


def test_persistent_source_failures_do_not_receive_an_extra_patch():
    source = 'Revenue was USD 12 million in 2024.'
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload('Revenue was USD 99 million in 2024.'))
    brief.items[0].evidence[0].text = source
    class Client:
        def generate_structured(self, *args, **kwargs): raise AssertionError('No source progress')
    errors = {'item_0':validate_executive_brief(brief, result, excerpts={1:source})}
    assert correct_residual_source_errors(Client(), brief, result=result, excerpts={1:source},
        initial_errors=errors, audit={}) is None


def test_partial_source_progress_then_residual_sign_and_meaning_corrections_complete():
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    source = 'Revenue was USD 12 million in 2024, unaudited. Expenses were USD -7 million in 2024, unaudited.'
    result = result_for([source])
    original = ExecutiveBrief.model_validate(payload('Revenue was USD 99 million in 2024.'))
    original.items[0].evidence[0].text = source
    original.items.append(original.items[0].model_copy(update={'label':'Expenses',
        'text':'Expenses were USD 9 million in 2024.'}))
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if self.calls == 1: return original
            if self.calls == 2:
                one, two = [i.model_dump() for i in original.items]
                one['text']='Revenue was USD 12 million in 2024.'
                two['text']='Expenses were USD 7 million in 2024.'
                return schema(item_0=one,item_1=two)
            if self.calls == 3:
                assert schema.__name__ == 'ExecutiveBriefPatch'
                assert set(schema.model_fields) == {'item_1'}
                return schema(item_1={'text':'Expenses were USD -7 million in 2024, unaudited.'})
            assert self.calls == 4
            assert set(schema.model_fields) == {'item_0'}
            return schema(item_0={'text':'Revenue was USD 12 million in 2024, unaudited.'})
    def meaning(brief):
        return {i:['Missing audit status.'] for i,item in enumerate(brief.items) if 'unaudited' not in item.text}
    client = Client()
    final = generate_with_item_repair(client, [{'role':'system','content':'Use evidence.'}],
        result=result, excerpts={1:source}, topics=[], source_context={}, semantic_validator=meaning)
    assert client.calls == 4
    assert not meaning(final) and not validate_executive_brief(final,result,excerpts={1:source})
    assert original.items[1].text == 'Expenses were USD 9 million in 2024.'
