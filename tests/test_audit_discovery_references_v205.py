"""Navigation addresses cannot corrupt or silently rebind retained observations."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.audit_discovery_references import (
    AuditDiscoveryReferenceError, reference_input, resolve_selection,
)
from adaptive_document_agent.agent.report_audit_source_discovery import (
    AuditSourceDiscovery, discover_audit_sources, validate_audit_source_discovery,
)
from adaptive_document_agent.agent.report_audit_source_index import discovery_input
from tests.test_audit_source_format_correction_v177 import case
from tests.test_budget_output_v145 import gateway, response


def test_short_references_preserve_complete_targets_and_sources_and_round_trip():
    result, base, valid = case()
    payload, _ = discovery_input(result, base)
    before = deepcopy(payload)
    wire, references = reference_input(payload)
    assert payload == before
    for original, sent in zip(payload['targets'], wire['targets']):
        assert references['targets'][sent['id']] == original['id']
        assert {**sent, 'id': original['id']} == original
    assert wire['page_index'] == payload['page_index']
    assert wire['already_read_source_pages'] == payload['already_read_source_pages']
    selected = valid.model_copy(deep=True)
    selected.ranges[0].section_id = wire['sections'][0]['id']
    selected.ranges[0].observation_ids = [wire['targets'][0]['id']]
    original = deepcopy(selected)
    assert resolve_selection(selected, references) == valid
    assert selected == original


def test_real_gateway_resolves_short_ids_before_source_validation_and_checkpoint_reuse():
    result, base, valid = case()
    payload, _ = discovery_input(result, base)
    wire, _ = reference_input(payload)
    selected = valid.model_copy(deep=True)
    selected.ranges[0].section_id = wire['sections'][0]['id']
    selected.ranges[0].observation_ids = [wire['targets'][0]['id']]
    llm, client = gateway([response(selected)])
    audit = {}
    expanded = discover_audit_sources(llm, result, base, audit)
    assert len(client.requests) == 1
    record = audit['source_discovery']
    assert record['selection'] == valid.model_dump(mode='json')
    assert record['attempts'][0]['model_selection'] == selected.model_dump(mode='json')
    assert record['reference_map']['targets'][selected.ranges[0].observation_ids[0]] == 'amount'
    validate_audit_source_discovery(result, expanded, record)


def test_exact_unknown_reference_is_identified_in_correction_not_fuzzy_rebound():
    result, base, valid = case()
    typo = valid.model_copy(deep=True)
    typo.ranges[0].observation_ids = ['amont']
    llm, client = gateway([response(typo), response(valid)])
    audit = {}
    expanded = discover_audit_sources(llm, result, base, audit)
    feedback = audit['source_discovery']['attempts'][0]['correction_feedback']
    issue = feedback['reference_issues'][0]
    assert issue['field'] == 'ranges[0].observation_ids'
    assert issue['unknown_references'] == ['amont']
    assert issue['allowed_references'] == ['t0', 't1']
    assert 'selection' not in audit['source_discovery']['attempts'][0]
    assert len(client.requests) == 2
    messages = client.requests[1][0]
    assert messages[:len(client.requests[0][0])] == client.requests[0][0]
    assert messages[-2]['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n')
    validate_audit_source_discovery(result, expanded, audit['source_discovery'])


def test_repeated_unknown_references_still_fail_after_one_correction():
    result, base, valid = case()
    valid.ranges[0].observation_ids = ['amont']
    llm, client = gateway([response(valid), response(valid)])
    audit = {}
    with pytest.raises(AuditDiscoveryReferenceError):
        discover_audit_sources(llm, result, base, audit)
    assert len(client.requests) == 2
    assert audit['source_discovery']['status'] == 'failed'
    assert audit['source_discovery']['attempts'][-1]['correction_budget_exhausted']


def test_duplicate_aliases_cannot_evade_unique_target_validation():
    _, _, valid = case()
    valid.ranges[0].observation_ids = ['t0', 'amount']
    with pytest.raises(AuditDiscoveryReferenceError) as raised:
        resolve_selection(valid, dict(targets={'t0': 'amount'},
                                      sections={'s0': valid.ranges[0].section_id}))
    assert raised.value.issues[0]['duplicate_observation_ids'] == ['amount']


def test_short_aliases_do_not_collide_with_retained_ids():
    result, base, _ = case()
    payload, _ = discovery_input(result, base)
    payload['targets'][0]['id'] = 't0'
    wire, references = reference_input(payload)
    assert 't0' not in references['targets']
    assert references['targets'][wire['targets'][0]['id']] == 't0'


def test_same_target_can_request_multiple_source_ranges_without_duplicate_rejection():
    _, _, valid = case()
    valid.ranges.append(valid.ranges[0].model_copy(deep=True))
    references = dict(targets={'t0': 'amount'}, sections={'s0': valid.ranges[0].section_id})
    for span in valid.ranges:
        span.observation_ids = ['t0']
        span.section_id = 's0'
    assert [r.observation_ids for r in resolve_selection(valid, references).ranges] == [['amount'], ['amount']]
