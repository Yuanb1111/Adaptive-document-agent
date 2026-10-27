"""Audit requests retain physical column evidence without assigning assurance."""
from copy import deepcopy
import json
import pytest

from adaptive_document_agent.agent.audit_source_layout import audit_source_page
from adaptive_document_agent.agent.report_audit_scope import (
    _context, review_report_audit_scope, reviewed_audit_bindings,
)
from adaptive_document_agent.agent.report_audit_source_index import discovery_input
from tests.test_report_audit_scope_v174 import fixture, Gateway
from tests.test_audit_source_discovery_v174 import unread_case, SelectionGateway


def add_layout(page):
    page.text_blocks = [dict(lines=[
        dict(text='2025', bbox=[210.1234, 100.4321, 230.5432, 110.1234]),
        dict(text='2025', bbox=[310.1234, 100.4321, 330.5432, 110.1234]),
        dict(text='(Unaudited)', bbox=[205.1234, 120.4321, 240.5432, 130.1234]),
    ])]


def test_all_valid_line_positions_survive_without_inferring_column_ownership():
    result, _ = fixture()
    page = result.document.pages[4]
    add_layout(page)
    page.text_blocks[0]['lines'].extend([
        'malformed line',
        dict(text='missing box'), dict(text='inverted', bbox=[4, 1, 2, 3]),
        dict(text='nonfinite', bbox=[0, 1, float('inf'), 3]),
        dict(text='not numeric', bbox=[0, 1, '2', 3]), dict(text='', bbox=[0, 1, 2, 3]),
    ])
    page.text_blocks.append(dict(lines='not a line list'))
    original = deepcopy(page.model_dump())
    source = audit_source_page(page)
    assert source == dict(page=5, text=page.text, layout_lines=[
        ['2025', 210.12, 230.54, 100.43], ['2025', 310.12, 330.54, 100.43],
        ['(Unaudited)', 205.12, 240.54, 120.43],
    ])
    assert page.model_dump() == original
    assert 'status' not in source and 'period' not in source
    assert audit_source_page(result.document.pages[0]) == dict(page=1, text=result.document.pages[0].text)


def test_context_and_both_independent_model_operations_receive_layout():
    result, binding = fixture()
    add_layout(result.document.pages[4])
    original = deepcopy((result.document, result.observations, result.analysis_results))
    gateway = Gateway(binding)
    review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 2
    for _, messages, _ in gateway.calls:
        assert 'layout_lines' in messages[1]['content']
        assert 'left x, right x, top y' in messages[0]['content']
        assert 'blank column does not establish audited' in messages[0]['content']
    assert 'Both audited and unaudited are valid proposed statuses' in gateway.calls[1][1][0]['content']
    assert (result.document, result.observations, result.analysis_results) == original
    assert set(reviewed_audit_bindings(result)) == {'amount'}
    result.document.pages[4].text_blocks[0]['lines'][0]['bbox'][0] += 2
    assert reviewed_audit_bindings(result) == {}


def test_discovered_pages_retain_positions_and_navigation_fingerprint_tracks_them():
    from adaptive_document_agent.agent.report_audit_source_discovery import discover_audit_sources
    result = unread_case()
    add_layout(result.document.pages[-1])
    base = _context(result)
    payload, fingerprint = discovery_input(result, base)
    assert payload['page_index'][-1]['complete_reading_chars'] > len(result.document.pages[-1].text)
    # Navigation carries complete read text; full geometry is reviewed after selection.
    assert all('layout_lines' not in p for p in payload['already_read_source_pages'])
    expanded = discover_audit_sources(SelectionGateway(), result, base, {})
    assert expanded['source_pages'][-1] == audit_source_page(result.document.pages[-1])
    result.document.pages[-1].text_blocks[0]['lines'][0]['bbox'][0] += 1
    next_payload, next_fingerprint = discovery_input(result, base)
    assert payload['page_index'] == next_payload['page_index']
    assert fingerprint != next_fingerprint


def test_line_geometry_counts_against_the_unchanged_full_review_budget(monkeypatch):
    from adaptive_document_agent.agent import report_audit_context_budget as budget
    result, _ = fixture()
    plain = _context(result)
    add_layout(result.document.pages[4])
    spatial = _context(result)
    plain_count = budget.audit_context_budget(plain)['largest_batch_characters']
    spatial_count = budget.audit_context_budget(spatial)['largest_batch_characters']
    assert spatial_count > plain_count
    monkeypatch.setattr(budget, 'MAX_AUDIT_CONTEXT_CHARS', spatial_count)
    budget.require_audit_context_budget(spatial)
    monkeypatch.setattr(budget, 'MAX_AUDIT_CONTEXT_CHARS', spatial_count - 1)
    with pytest.raises(ValueError, match='no page was truncated'):
        budget.require_audit_context_budget(spatial)
    assert budget.require_audit_context_budget(plain)


def test_budget_measures_the_identical_lossless_context_sent_to_both_reviewers():
    from adaptive_document_agent.agent.report_audit_context_budget import serialize_audit_context
    result, binding = fixture()
    add_layout(result.document.pages[4])
    gateway = Gateway(binding)
    review_report_audit_scope(gateway, result)
    context = _context(result)
    for _, messages, _ in gateway.calls:
        encoded = messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]
        decoded = json.loads(encoded)
        assert encoded == serialize_audit_context(decoded)
        assert decoded['source_pages'] == context['source_pages']
        assert len(encoded) < len(json.dumps(decoded, ensure_ascii=False))
        assert decoded['observations'] == context['observations']


def test_spatial_aid_omits_wide_prose_geometry_without_dropping_its_source_text():
    result, _ = fixture()
    page = result.document.pages[4]
    add_layout(page)
    prose = 'Full-width qualification remains in complete source text, including its period and entity.'
    page.text += '\n' + prose
    page.text_blocks[0]['lines'].append(dict(text=prose, bbox=[0, 200, 500, 220]))
    before = deepcopy(page)
    source = audit_source_page(page)
    assert prose in source['text']
    assert prose not in [line[0] for line in source['layout_lines']]
    assert [line[0] for line in source['layout_lines']] == ['2025', '2025', '(Unaudited)']
    assert page == before
