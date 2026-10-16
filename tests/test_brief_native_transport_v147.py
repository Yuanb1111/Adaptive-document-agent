"""Bounded first-draft options retain later source blocks and complete native units."""
import json

from adaptive_document_agent.agent.brief_native_transport import source_quantity_options, _compact
from adaptive_document_agent.agent.executive_brief import _source_quantity_options
from tests.test_brief_table_context import table_result


def test_later_literal_table_refs_receive_exact_options_without_copying_other_source():
    result, _ = table_result()
    text = result.document.pages[0].text
    blocks = {f'p1_b{i}': {'page': 1, 'text': f'Literal introductory passage {i} without amounts.'}
              for i in range(1, 7)}
    blocks['p1_b7'] = {'page': 1, 'text': text}
    # Supply those exact passages in their original order as the source excerpt.
    result.document.pages[0].text = '\n\n'.join(block['text'] for block in blocks.values())
    excerpts = {1: result.document.pages[0].text}
    rows = _source_quantity_options(result, excerpts, blocks)
    assert any(option['amount_text'] == 'US$ 1475 thousand' for row in rows for option in row['quantities'])
    assert any('p1_b7' in row['evidence_refs'] for row in rows)
    assert all(len(row['evidence_refs']) <= 4 for row in rows)
    assert len(json.dumps(rows, ensure_ascii=False)) <= 18000


def test_small_transport_budget_keeps_some_options_instead_of_dropping_whole_page():
    result, _ = table_result()
    text = result.document.pages[0].text
    rows = source_quantity_options(result, {1: text}, {'ref': {'page': 1, 'text': text}}, character_limit=170)
    assert rows and rows[0]['quantities']
    assert len(json.dumps(rows, ensure_ascii=False)) <= 170


def test_compact_spelling_keeps_exact_denominator_and_magnitude_annotation():
    option = {'amount_text': 'USD -12 thousand', 'literal_basis': ['unit'],
        'magnitude_option': {'amount_text': 'USD 12 thousand', 'quantity_representation': {
            'quantity_text': 'USD 12 thousand', 'source_value': '-12', 'representation': 'absolute_magnitude'}}}
    compact = _compact(option)
    assert compact['amount_text'] == 'USD -12 thousand per unit'
    magnitude = compact['magnitude_option']
    assert magnitude['amount_text'] == magnitude['quantity_representation']['quantity_text'] == 'USD 12 thousand per unit'
    assert option['amount_text'] == 'USD -12 thousand'
