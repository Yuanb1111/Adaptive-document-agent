import pytest

from adaptive_document_agent.agent.brief_semantic_repair import correct_new_meaning_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from tests.test_executive_brief import result_for, payload


def test_displayed_quantity_contract_keeps_signed_source_scale_without_conversion():
    from adaptive_document_agent.agent.brief_meaning_contract import displayed_quantity_contract
    brief = ExecutiveBrief.model_validate(payload('Cash outflow was RMB -70414 thousand in 1H2024.'))
    contract = displayed_quantity_contract(brief.items[0])
    assert dict(currency='rmb', signed_coefficient='-70414', unit='thousand',
                amount_text='RMB -70414 thousand') in contract
    assert not any(row['unit'] == 'million' for row in contract)


@pytest.mark.parametrize('invented_label', [False, True])
def test_meaning_repair_can_fix_rejected_label_but_cannot_add_label_quantities(invented_label):
    source = 'Loss was USD 12 million in 2023 and USD 24 million in 2024.'
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload(source))
    brief.items[0].label = 'Loss narrowed'
    brief.items[0].evidence[0].text = source
    locked = brief.items[0].model_copy(update={'label': 'Reported amounts',
                                              'text': 'The source reports annual losses.'})
    brief.items.append(locked)
    reviewed = []
    def meaning(value):
        reviewed.append(value)
        return {0: ['Label contradicts loss magnitude.']} if value.items[0].label == 'Loss narrowed' else {}
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            assert set(schema.model_fields) == {'item_0'}
            return schema(item_0=dict(text=source,
                label='Loss widened to USD 99 million' if invented_label else 'Loss widened'))
    audit = {}
    corrected = correct_new_meaning_errors(Client(), brief, result=result, excerpts={1: source},
        topics=[], source_context={}, evidence_catalog=None, semantic_validator=meaning, audit=audit)
    if invented_label:
        assert corrected is None
        assert len(reviewed) == 1
        assert 'introduced new quantities' in str(audit)
    else:
        assert corrected.items[0].label == 'Loss widened'
        assert corrected.items[1] == locked
        assert len(reviewed) == 2


@pytest.mark.parametrize('valid', [True, False])
def test_post_source_meaning_patch_is_bounded_locks_good_items_and_rechecks_sources(valid):
    source = 'Revenue was USD 12 million in 2024, unaudited.'
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload('Revenue was USD 12 million in 2024.'))
    brief.items[0].evidence[0].text = source
    locked = brief.items[0].model_copy(update={'label': 'Source status',
                                            'text': 'The reported 2024 figures were unaudited.'})
    brief.items.append(locked)
    reviewed = []
    def meaning(value):
        reviewed.append(value)
        return {} if 'unaudited' in value.items[0].text else {0: ['Missing unaudited qualification.']}
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert set(schema.model_fields) == {'item_0'}
            replacement = brief.items[0].model_dump()
            replacement['text'] = 'Revenue was USD ' + ('12' if valid else '99') + ' million in 2024, unaudited.'
            return schema(item_0={'text': replacement['text']})
    client, audit = Client(), {}
    corrected = correct_new_meaning_errors(client, brief, result=result, excerpts={1: source}, topics=[],
        source_context={}, evidence_catalog=None, semantic_validator=meaning, audit=audit)
    assert client.calls == 1
    if valid:
        assert corrected.items[1] == locked
        assert len(reviewed) == 2
        assert audit['post_source_meaning_correction']['status'] == 'accepted'
    else:
        assert corrected is None
        assert len(reviewed) == 1
        assert audit['post_source_meaning_correction']['status'] == 'rejected'


def test_source_repair_then_new_meaning_failure_receives_one_separate_correction():
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    source = 'Revenue was USD 12 million in 2024, unaudited.'
    result = result_for([source])
    original = ExecutiveBrief.model_validate(payload('Revenue was USD 99 million in 2024.'))
    original.items[0].evidence[0].text = source
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return original
            replacement = original.items[0].model_dump()
            replacement['text'] = 'Revenue was USD 12 million in 2024' + (', unaudited.' if self.calls == 3 else '.')
            return schema(item_0={'text': replacement['text']} if self.calls == 3 else replacement)
    def meaning(value):
        return {} if 'unaudited' in value.items[0].text else {0: ['Missing source audit status.']}
    client = Client()
    corrected = generate_with_item_repair(client, [{'role': 'system', 'content': 'Use source evidence.'}],
        result=result, excerpts={1: source}, topics=[], source_context={}, semantic_validator=meaning)
    assert client.calls == 3
    assert 'unaudited' in corrected.items[0].text


def test_terminal_error_reports_latest_meaning_failure_and_retains_earlier_feedback():
    import json
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    source = 'Revenue was USD 12 million in 2024, unaudited.'
    result = result_for([source])
    original = ExecutiveBrief.model_validate(payload('Revenue was USD 99 million in 2024.'))
    original.items[0].evidence[0].text = source

    class Client:
        calls = 0

        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return original
            replacement = original.items[0].model_dump()
            replacement['text'] = 'Revenue was USD 12 million in 2024' + (', unaudited.' if self.calls == 3 else '.')
            return schema(item_0={'text': replacement['text']} if self.calls == 3 else replacement)

    def meaning(value):
        return {0: ['Comparison does not bind an exact audience claim' if 'unaudited' in value.items[0].text
                    else 'Missing source audit status.']}

    with pytest.raises(ValueError, match='exact audience claim') as exc:
        generate_with_item_repair(Client(), [{'role': 'system', 'content': 'Use source evidence.'}],
            result=result, excerpts={1: source}, topics=[], source_context={}, semantic_validator=meaning)
    assert 'Missing source audit status' not in str(exc.value)
    audit = json.loads(next(w.message for w in result.validation_warnings if w.code == 'executive_brief_repair_audit'))
    assert audit['pre_meaning_correction_errors'] == ['Missing source audit status.']
    assert audit['repair_errors'] == ['Comparison does not bind an exact audience claim']


@pytest.mark.parametrize('persistent', [True, False])
def test_meaning_patch_format_retry_keeps_source_and_stops_after_one_retry(persistent):
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    source = 'Revenue was USD 12 million in 2024, unaudited.'
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload('Revenue was USD 12 million in 2024.'))
    brief.items[0].evidence[0].text = source
    class Client:
        calls = 0
        initial = None
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if self.calls == 1:
                self.initial = messages[1]
            else:
                assert messages[1] == self.initial
                assert 'SAME targeted' in messages[-1]['content']
            if persistent or self.calls == 1:
                raise LLMStructuredOutputError('Invalid text length', response=LLMResponse(text='{"item_0": {}}'))
            item = brief.items[0].model_dump()
            item['text'] += ' The figures were unaudited.'
            return schema(item_0={'text': item['text']})
    def meaning(value):
        return {} if 'unaudited' in value.items[0].text else {0: ['Audit status missing.']}
    client, audit = Client(), {}
    args = dict(result=result, excerpts={1: source}, topics=[], source_context={}, evidence_catalog=None,
                semantic_validator=meaning, audit=audit)
    if persistent:
        with pytest.raises(LLMStructuredOutputError):
            correct_new_meaning_errors(client, brief, **args)
    else:
        assert correct_new_meaning_errors(client, brief, **args)
    assert client.calls == 2
