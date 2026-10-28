"""Large navigation requests remove key overhead, never pages or source values."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent import report_audit_source_index as index
from adaptive_document_agent.agent.audit_discovery_references import reference_input
from adaptive_document_agent.agent.report_audit_context_budget import require_audit_context_budget
from adaptive_document_agent.agent.report_audit_scope import _context
from adaptive_document_agent.agent.report_audit_source_discovery import (
    AuditSourceDiscovery, discover_audit_sources, validate_audit_source_discovery,
)
from tests.test_budget_output_v145 import gateway, response
from tests.test_report_audit_batches_v174 import many_targets


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def large_navigation():
    result, _ = many_targets(91)
    for number in range(8, 525):
        result.document.pages.append(result.document.pages[0].model_copy(deep=True,
            update=dict(page_number=number, text='Complete source navigation 120,462. ' * 8)))
    result.document.page_count = 524
    payload, _ = index.discovery_input(result, _context(result))
    wire, _ = reference_input(payload)
    padding = 279_198 - len(encoded(wire))
    assert padding > 0
    result.document.pages[0].text += 'x' * padding
    return result, _context(result)


def test_large_request_reaches_real_gateway_with_all_91_targets_and_524_pages():
    result, base = large_navigation()
    before = deepcopy((result, base))
    require_audit_context_budget(base)
    payload, _ = index.discovery_input(result, base)
    original, references = reference_input(payload)
    assert len(encoded(original)) > index.MAX_DISCOVERY_INPUT_CHARS
    request, actual_references = index.discovery_request(payload)
    wire = json.loads(request)
    assert len(request) <= index.MAX_DISCOVERY_INPUT_CHARS
    assert actual_references == references
    table = wire['page_index']
    restored = [dict(zip(table['columns'], row)) for row in table['rows']]
    assert restored == original['page_index'] and len(restored) == 524
    assert len(wire['targets']) == 91
    for key in original.keys() - {'page_index', 'navigation_notice'}:
        assert wire[key] == original[key]
    assert wire['navigation_notice'].startswith(original['navigation_notice'])

    # Navigate to an actual unread page using the short IDs, through LLMGateway.
    section = next(s for s in original['sections'] if s['start_page'] <= 524 <= s['end_page'])
    selection = AuditSourceDiscovery(ranges=[dict(section_id=section['id'], start_page=524,
        end_page=524, observation_ids=[original['targets'][0]['id']],
        reason='Inspect the full original row on the last indexed page.')],
        rationale='Navigation alone does not establish the assurance of any target.')
    llm, client = gateway([response(selection)])
    audit = {}
    expanded = discover_audit_sources(llm, result, base, audit)
    source_message = next(m['content'] for m in client.requests[0][0]
                          if m['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n'))
    sent = source_message.split('\n', 1)[1].rsplit('\n', 1)[0]
    assert sent == request and len(client.requests) == 1
    assert audit['source_discovery']['serialized_input_characters'] == len(request)
    assert expanded['source_pages'][-1]['text'] == result.document.pages[-1].text
    assert expanded['source_discovery']['added_pages'] == [524]
    validate_audit_source_discovery(result, expanded, audit['source_discovery'])
    assert expanded['observations'] == base['observations']
    assert not {'ledger', 'review'} & audit.keys()
    assert (result, base) == before


def test_column_table_preserves_optional_fields_hits_and_literal_unicode_spacing():
    result, base = large_navigation()
    payload, _ = index.discovery_input(result, base)
    payload['page_index'][0]['navigation_preview'] = '  页码\n– I-5 –\t"原文"  '
    payload['page_index'][0]['complete_reading_chars'] = 12345
    before = deepcopy(payload)
    wire, _ = reference_input(payload)
    table = json.loads(encoded(index._columnar_navigation(wire)))['page_index']
    assert [dict(zip(table['columns'], row)) for row in table['rows']] == wire['page_index']
    assert len(table['rows'][0]) == 5 and len(table['rows'][1]) == 4
    assert payload == before


def test_unknown_navigation_fields_fail_instead_of_silently_disappearing():
    result, base = large_navigation()
    payload, _ = index.discovery_input(result, base)
    payload['page_index'][0]['new_evidence_field'] = 'Must not disappear'
    with pytest.raises(ValueError, match='Unknown audit navigation fields'):
        index.discovery_request(payload)


def test_unread_body_change_still_expires_compact_navigation_selection():
    result, base = large_navigation()
    payload, fingerprint = index.discovery_input(result, base)
    result.document.pages[-1].text += '\nChanged source qualification beyond the preview.'
    changed, next_fingerprint = index.discovery_input(result, base)
    assert changed['page_index'][-1]['navigation_preview'] == payload['page_index'][-1]['navigation_preview']
    assert next_fingerprint != fingerprint
