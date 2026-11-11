import pytest

from adaptive_document_agent.agent.brief_semantic_repair import correct_new_meaning_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from tests.test_executive_brief import result_for, payload


def test_initial_meaning_review_includes_source_invalid_items_before_quantities_lock():
    from adaptive_document_agent.agent.brief_item_repair import _classify
    source = 'Revenue was USD 12 million in 2024. The complementary rate was 75.8%.'
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload('Revenue was USD 12 million in 2024.'))
    brief.items[0].evidence[0].text = source
    brief.items.append(brief.items[0].model_copy(update={
        'label': 'Companion finding', 'text': 'Revenue was USD 99 million in 2024.'}))
    def meaning(candidate):
        assert candidate.items == brief.items
        return {1: ['The missing complementary rate materially qualifies this conclusion.']}
    locked, invalid, _ = _classify(brief.model_dump(mode='json'), result, {1: source}, meaning)
    assert set(locked) == {0} and set(invalid) == {1}
    assert any('unsupported' in reason or 'amount changes' in reason for reason in invalid[1])
    assert invalid[1][-1] == 'Meaning review: The missing complementary rate materially qualifies this conclusion.'


def test_rotated_quote_coordinates_keep_same_column_events_together_without_uncited_text():
    from adaptive_document_agent.agent.brief_quote_layout import quoted_layout
    source = '2028 Partner trials Start production'
    result = result_for([source])
    page = result.document.pages[0]
    page.reading_rotation = 90
    page.text_blocks = [{'lines': None}, {'lines': [
        {'bbox': box, 'text': text} for box, text in [
            ([10, 35, 15, 45], '2028'), ([20, 32, 25, 50], 'Partner trials'),
            ([30, 32, 35, 50], 'Start production'), ([30, 0, 35, 10], 'Uncited text')]]}]
    item = ExecutiveBrief.model_validate(payload(source)).items[0]
    lines = quoted_layout(item, result)[0]['lines']
    assert [line[3] for line in lines] == ['2028', 'Partner trials', 'Start production']
    assert lines[1][1:3] == lines[2][1:3] == [-50, -32]


def test_review_can_restore_the_referenced_literal_qualification_without_changing_other_items():
    from adaptive_document_agent.agent.brief_semantic_repair import _bind_reviewed_passages
    from adaptive_document_agent.models.executive_brief import BRIEF_EVIDENCE_LIMIT
    brief = ExecutiveBrief.model_validate(payload('The measure is 15 in 2024.'))
    brief.items.append(brief.items[0].model_copy(deep=True))
    catalog = {'p2_b3': {'page': 2, 'text': 'The measure excludes trial participants.'},
               'p2_b4': {'page': 2, 'text': 'This wording is absent from the source.'}}
    excerpts = {2: catalog['p2_b3']['text']}
    issues = {1: ['Check p2_b3 and p2_b4. See p2_b3 also.']}
    changed, refs = _bind_reviewed_passages(brief, issues, catalog, excerpts)
    assert refs == {1: ['p2_b3']} and changed.items[0] == brief.items[0]
    assert changed.items[1].evidence[:-1] == brief.items[1].evidence
    assert changed.items[1].evidence[-1].model_dump() == catalog['p2_b3']
    brief.items[1].evidence *= BRIEF_EVIDENCE_LIMIT
    assert _bind_reviewed_passages(brief, issues, catalog, excerpts) == (brief, {})


def test_displayed_quantity_contract_keeps_signed_source_scale_without_conversion():
    from adaptive_document_agent.agent.brief_meaning_contract import displayed_quantity_contract
    brief = ExecutiveBrief.model_validate(payload('Cash outflow was RMB -70414 thousand in 1H2024.'))
    contract = displayed_quantity_contract(brief.items[0])
    assert dict(currency='rmb', signed_coefficient='-70414', unit='thousand',
                amount_text='RMB -70414 thousand') in contract
    assert not any(row['unit'] == 'million' for row in contract)


@pytest.mark.parametrize('addition,retry', [
    ('Turnover increased in the six months ended June 30, 2024.', True),
    ('Turnover increased in the six months ended December 31, 2024.', False),
    ('Turnover increased over six months.', False),
    ('Turnover increased in the six months ended June 30, 2024; six units remained.', False),
])
def test_new_quoted_flow_period_gets_only_a_removal_retry(addition, retry):
    from adaptive_document_agent.agent.brief_meaning_contract import check_meaning_contract
    from adaptive_document_agent.agent.brief_audit_scope import source_audit_scope
    source = ('Inventory was 15 at 2024-06-30. '
              'Turnover increased in the six months ended June 30, 2024.')
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload('Inventory was 15 at 2024-06-30.'))
    brief.items[0].evidence[0].text = source
    candidate = brief.model_copy(deep=True)
    candidate.items[0].text += ' ' + addition
    _, errors, feedback, recoverable = check_meaning_contract(
        brief, candidate, [0], result=result, excerpts={1: source},
        inventories={0: source_audit_scope(brief.items[0], result)}, periods={0: []})
    # Exact quotation grants a retry asking for removal, never acceptance.
    assert any('introduced new quantities' in error for error in errors)
    assert recoverable is retry
    assert feedback['item_0']['new_period_wording_to_remove'] == ([('', '6', '')] if retry else [])


def test_quoted_new_period_is_removed_before_fresh_meaning_review():
    source = ('Inventory was 15 at 2024-06-30. Management assessed NRV. '
              'Turnover increased in the six months ended June 30, 2024.')
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload('Inventory was 15 at 2024-06-30.'))
    brief.items[0].evidence[0].text = source
    reviewed = []
    def meaning(value):
        reviewed.append(value)
        return {} if 'Management assessed NRV.' in value.items[0].text else {0: ['Keep the NRV qualification.']}
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            text = brief.items[0].text + ' Management assessed NRV.'
            if self.calls == 1:
                text += ' Turnover increased in the six months ended June 30, 2024.'
            else:
                assert 'new_period_wording_to_remove' in str(messages)
            return schema(item_0=dict(text=text))
    client, audit = Client(), {}
    corrected = correct_new_meaning_errors(client, brief, result=result, excerpts={1: source},
        topics=[], source_context={}, evidence_catalog=None, semantic_validator=meaning, audit=audit)
    assert client.calls == 2 and len(reviewed) == 2
    assert corrected.items[0].text == brief.items[0].text + ' Management assessed NRV.'
    assert audit['post_source_meaning_correction']['status'] == 'accepted'


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
            import json
            context = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert context['earlier_review_questions'] == {'item_0': ['Meaning review: Preserve the reconciliation.']}
            assert set(schema.model_fields) == {'item_0'}
            return schema(item_0=dict(text=source,
                label='Loss widened to USD 99 million' if invented_label else 'Loss widened'))
    audit = {'meaning_source_indices': [1, 2], 'initial_errors': {
        'item_0': ['Meaning review: A different finding.'],
        'item_1': ['Meaning review: Preserve the reconciliation.', 'Unrelated format error.']}}
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


def test_a_failed_meaning_sibling_retains_source_valid_candidates_for_fresh_salvage_review():
    from adaptive_document_agent.agent.brief_item_repair import _salvage
    source = 'Loss was USD 12 million in 2023 and USD 24 million in 2024.'
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload(source))
    brief.items[0].label = 'Incorrect first label'
    brief.items.append(brief.items[0].model_copy(update={
        'label': 'Incorrect second label', 'text': 'Reported loss was USD 12 million in 2023.'}))
    brief.items.append(brief.items[0].model_copy(update={
        'label': 'Risk', 'text': 'The source reports annual losses.'}))
    def meaning(value):
        return {i: ['Incorrect label.'] for i, item in enumerate(value.items) if item.label.startswith('Incorrect')}
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            return schema(item_0=dict(text=source, label='Loss widened'),
                          item_1=dict(text=source, label='Loss widened to USD 99 million'))
    audit = {}
    assert correct_new_meaning_errors(Client(), brief, result=result, excerpts={1: source},
        topics=[], source_context={}, evidence_catalog=None, semantic_validator=meaning, audit=audit) is None
    candidates = audit['post_source_meaning_correction']['source_valid_candidates']
    assert set(candidates) == {'0'}
    merged = brief.model_dump(mode='json')['items']
    merged[0] = candidates['0']
    checked = []
    def independent(value):
        checked.append(value)
        return meaning(value)
    kept, rejected = _salvage(merged, {2: brief.items[2]}, brief.title, result, {1: source}, [], independent)
    assert kept.items[0].label == 'Loss widened' and rejected == [1] and checked


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
