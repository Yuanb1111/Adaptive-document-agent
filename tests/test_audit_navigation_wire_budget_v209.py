"""Navigation admission measures the exact lossless payload sent to the gateway."""
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
from tests.test_report_audit_batches_v174 import many_targets


def near_boundary_case():
    result, _ = many_targets(68)
    for number in range(8, 525):
        result.document.pages.append(result.document.pages[0].model_copy(deep=True,
            update=dict(page_number=number, text='Complete navigation preview. ' * 8)))
    result.document.page_count = 524
    payload, _ = index.discovery_input(result, _context(result))
    padding = index.MAX_DISCOVERY_INPUT_CHARS + 1 - len(json.dumps(payload, ensure_ascii=False))
    assert padding > 0
    result.document.pages[0].text += 'x' * padding
    return result, _context(result)


def test_large_navigation_preserves_all_68_targets_524_pages_and_exact_source_text():
    result, base = near_boundary_case()
    before = deepcopy((result, base))
    require_audit_context_budget(base)
    payload, _ = index.discovery_input(result, base)
    assert len(json.dumps(payload, ensure_ascii=False)) > index.MAX_DISCOVERY_INPUT_CHARS
    encoded, references = index.discovery_request(payload)
    wire, expected_references = reference_input(payload)
    assert json.loads(encoded) == wire
    assert references == expected_references
    assert len(encoded) < index.MAX_DISCOVERY_INPUT_CHARS
    assert len(wire['targets']) == 68 and len(wire['page_index']) == 524
    assert wire['already_read_source_pages'] == base['source_pages']

    class Gateway:
        calls = 0

        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert schema is AuditSourceDiscovery
            sent = messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]
            assert sent == encoded
            return schema(rationale='No additional counterpart located; this grants no assurance.')

    gateway, audit = Gateway(), {}
    expanded = discover_audit_sources(gateway, result, base, audit)
    assert gateway.calls == 1
    assert audit['source_discovery']['serialized_input_characters'] == len(encoded)
    validate_audit_source_discovery(result, expanded, audit['source_discovery'])
    assert expanded['observations'] == base['observations']
    assert expanded['source_pages'] == base['source_pages']
    assert 'ledger' not in audit and 'review' not in audit
    assert (result, base) == before


def test_exact_wire_boundary_is_admitted_but_one_character_over_still_blocks(monkeypatch):
    result, base = near_boundary_case()
    before = deepcopy((result, base))
    payload, _ = index.discovery_input(result, base)
    encoded, _ = index.discovery_request(payload)
    monkeypatch.setattr(index, 'MAX_DISCOVERY_INPUT_CHARS', len(encoded))
    assert index.discovery_input(result, base)[0] == payload
    # v213 can remove repeated navigation keys before rejecting the request.
    wire, _ = reference_input(payload)
    compact = json.dumps(index._columnar_navigation(wire), ensure_ascii=False, separators=(',', ':'))
    monkeypatch.setattr(index, 'MAX_DISCOVERY_INPUT_CHARS', len(compact))
    assert index.discovery_request(payload)[0] == compact
    monkeypatch.setattr(index, 'MAX_DISCOVERY_INPUT_CHARS', len(compact) - 1)

    class NoCall:
        def generate_structured(self, *args, **kwargs):
            raise AssertionError('An oversized wire payload cannot reach a model.')

    audit = {}
    with pytest.raises(ValueError, match='serialized characters.*no index entries were dropped'):
        discover_audit_sources(NoCall(), result, base, audit)
    assert audit['source_discovery']['status'] == 'failed'
    assert not audit['source_discovery']['attempts']
    assert (result, base) == before


def test_compact_transport_preserves_whitespace_inside_source_values_and_source_identity():
    result, base = near_boundary_case()
    result.document.pages[0].text += '\n  Exact spacing, : and \\"quoted\\" text.\n'
    base = _context(result)
    payload, original_fingerprint = index.discovery_input(result, base)
    encoded, _ = index.discovery_request(payload)
    assert json.loads(encoded)['already_read_source_pages'] == base['source_pages']
    # An unread body change outside the preview still expires the full-source hash.
    result.document.pages[-1].text = result.document.pages[-1].text[:-1] + '!'
    changed, changed_fingerprint = index.discovery_input(result, base)
    assert changed['page_index'] == payload['page_index']
    assert original_fingerprint != changed_fingerprint
