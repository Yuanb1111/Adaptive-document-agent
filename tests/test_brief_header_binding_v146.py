"""A quoted data row retains its own literal headers through meaning review."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_table_headers import bind_table_headers
from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
from tests.test_brief_table_context import table_result


def test_complete_row_adds_exact_source_header_without_changing_claim_or_quote():
    result, brief = table_result()
    item = brief.items[0].model_dump(mode='json')
    before = deepcopy(item)
    excerpts = {1: result.document.pages[0].text}
    bound, audit = bind_table_headers(item, result, excerpts)
    assert item == before
    assert bound['text'] == before['text']
    assert bound['evidence'][:-1] == before['evidence']
    assert bound['evidence'][-1] == {'page': 1, 'text': '\n'.join(result.document.pages[0].tables[0].raw_header_lines)}
    assert audit[0]['table_id'] == 'fees'
    assert bind_table_headers(bound, result, excerpts) == (bound, [])


@pytest.mark.parametrize('case', ['partial', 'ambiguous', 'missing_header', 'wrong_page',
                                 'discontinuous', 'unresolved', 'quote_limit'])
def test_unproven_context_never_acquires_a_header(case):
    result, brief = table_result()
    item = brief.items[0].model_dump(mode='json')
    page = result.document.pages[0]
    excerpts = {1: page.text}
    if case == 'partial':
        item['evidence'][0]['text'] = 'Programme fees . . . 1,250'
    elif case == 'ambiguous':
        other = page.tables[0].model_copy(deep=True)
        other.table_id = 'other'
        other.column_currencies = [None, 'EUR', 'EUR']
        page.tables.append(other)
    elif case == 'missing_header':
        page.tables[0].raw_header_lines.append('Invented source condition')
    elif case == 'wrong_page':
        item['evidence'][0]['page'] = 2
    elif case == 'discontinuous':
        excerpts[1] = page.text.replace('2023 2024', '[SEPARATE SOURCE PASSAGE]\n2023 2024')
    elif case == 'unresolved':
        page.tables[0].rows[0].alignment_status = 'ambiguous'
    else:
        item['evidence'] *= 4
    before = deepcopy(item)
    assert bind_table_headers(item, result, excerpts) == (before, [])


def test_independent_meaning_review_receives_bound_headers_before_acceptance():
    result, brief = table_result()
    excerpts = {1: result.document.pages[0].text}
    class Gateway:
        calls = 0
        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            assert self.calls == 1
            return brief
    def meaning(current):
        quotes = ' '.join(q.text for q in current.items[0].evidence)
        assert '2023 2024' in quotes and '(USD in thousands)' in quotes
        return {}
    gateway = Gateway()
    final = generate_with_item_repair(gateway, [{'role': 'system', 'content': 'Use literal evidence.'}],
        result=result, excerpts=excerpts, topics=[], source_context={}, semantic_validator=meaning)
    assert len(final.items[0].evidence) == 2 and gateway.calls == 1
    audit = next(w for w in result.validation_warnings if w.code == 'executive_brief_repair_audit')
    payload = json.loads(audit.message)
    assert audit.severity == 'info' and payload['outcome'] == 'table_context_bound'
    assert payload['before_table_context_binding'] == brief.model_dump(mode='json')
    assert payload['table_context_bindings'][0]['table_id'] == 'fees'


@pytest.mark.parametrize('page', [[], {}, None, True, 0, -1, '1'])
def test_malformed_page_stays_available_for_item_repair_without_binding(page):
    result, brief = table_result()
    item = brief.items[0].model_dump(mode='json')
    item['evidence'][0]['page'] = page
    before = deepcopy(item)
    assert bind_table_headers(item, result, {1: result.document.pages[0].text}) == (before, [])
