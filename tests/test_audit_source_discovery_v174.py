"""Model-selected full-page reading invalidates incomplete audit contexts."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import _context, review_report_audit_scope
from adaptive_document_agent.agent.report_audit_source_discovery import (
    AuditSourceDiscovery, discover_audit_sources, validate_audit_source_discovery,
)
from adaptive_document_agent.agent.report_audit_source_index import discovery_input
from adaptive_document_agent.models import ValidationIssue
from tests.test_report_audit_scope_v174 import fixture


def unread_case():
    result, _ = fixture()
    for number, text in [(8, 'Related statements continuation, including full header and units.'),
                         (9, 'Related exact amounts. ' + 'Navigation filler ' * 20 +
                          '\nUNREAD_BODY_SENTINEL Revenue 120,462. Complete page footer.')]:
        result.document.pages.append(result.document.pages[0].model_copy(deep=True,
            update=dict(page_number=number, text=text)))
    result.document.page_count = 9
    return result


class SelectionGateway:
    def __init__(self, *, wrong_section=False, no_additions=False):
        self.calls = []
        self.wrong_section, self.no_additions = wrong_section, no_additions

    def generate_structured(self, messages, schema, **kwargs):
        assert schema is AuditSourceDiscovery
        self.calls.append((deepcopy(messages), kwargs))
        payload = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        assert [p['page'] for p in payload['page_index']] == list(range(1, 10))
        assert len(payload['targets']) == 2
        assert 'UNREAD_BODY_SENTINEL' not in messages[1]['content']
        assert 0 in payload['page_index'][8]['literal_raw_value_target_indices']
        return schema(ranges=[] if self.no_additions else [dict(
            section_id='invented' if self.wrong_section else payload['sections'][0]['id'],
            start_page=8, end_page=9, observation_ids=['amount'],
            reason='Read the original counterpart row with its preceding complete table header.')],
            rationale='Locate exact counterpart evidence; navigation matches are not assurance.')


def test_complete_index_selects_full_pages_without_uploading_unselected_page_bodies():
    result = unread_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    base, audit, gateway = _context(result), {}, SelectionGateway()
    expanded = discover_audit_sources(gateway, result, base, audit)
    assert len(gateway.calls) == 1 and gateway.calls[0][1]['stage'] == 'report'
    assert gateway.calls[0][1]['allow_repair'] is False
    assert expanded['source_pages'][-1]['text'] == result.document.pages[-1].text
    assert expanded['source_discovery']['added_pages'] == [8, 9]
    assert audit['source_discovery']['status'] == 'complete'
    validate_audit_source_discovery(result, expanded, audit['source_discovery'])
    assert (result.document, result.observations, result.analysis_results) == original
    assert base == _context(result)


def test_same_full_source_discovery_can_resume_from_latest_failed_checkpoint():
    result = unread_case()
    base, audit = _context(result), {}
    expanded = discover_audit_sources(SelectionGateway(), result, base, audit)
    result.validation_warnings.append(ValidationIssue(code='report_audit_scope_unresolved',
        severity='warning', stage='report', message=json.dumps(audit)))
    class NoNewCall:
        def generate_structured(self, *args, **kwargs):
            raise AssertionError('A complete unchanged selection should resume without another request.')
    replay = {}
    assert discover_audit_sources(NoNewCall(), result, base, replay) == expanded
    assert replay['source_discovery'] == audit['source_discovery']


def test_unread_source_body_change_expires_discovery_even_if_navigation_preview_does_not_change():
    result = unread_case()
    base, audit = _context(result), {}
    expanded = discover_audit_sources(SelectionGateway(no_additions=True), result, base, audit)
    old_input, old_fingerprint = discovery_input(result, base)
    result.document.pages[-1].text = result.document.pages[-1].text.replace('UNREAD_BODY', 'ALTERD_BODY')
    new_input, new_fingerprint = discovery_input(result, base)
    assert old_input['page_index'] == new_input['page_index']
    assert old_input['document_source_fingerprint'] != new_input['document_source_fingerprint']
    assert old_fingerprint != new_fingerprint
    with pytest.raises(ValueError, match='stale'):
        validate_audit_source_discovery(result, expanded, audit['source_discovery'])


def test_discovery_is_required_even_for_a_previously_accepted_context():
    result = unread_case()
    with pytest.raises(ValueError, match='missing or unfinished'):
        validate_audit_source_discovery(result, _context(result), None)


def test_invalid_range_has_only_one_correction_and_saves_reporting_retry_diagnostics():
    result = unread_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    gateway = SelectionGateway(wrong_section=True)
    with pytest.raises(ValueError, match='indexed section'):
        review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 2
    warning = result.validation_warnings[-1]
    assert warning.code == 'report_audit_scope_unresolved'
    audit = json.loads(warning.message)
    assert audit['source_discovery']['status'] == 'failed'
    assert len(audit['source_discovery']['attempts']) == 2
    assert audit['batches'] == []
    assert (result.document, result.observations, result.analysis_results) == original


def test_oversize_selected_page_is_never_truncated_or_silently_treated_as_read():
    result = unread_case()
    result.document.pages[-1].text += 'x' * 150_000
    original = deepcopy(result.document)
    audit, gateway = {}, SelectionGateway()
    with pytest.raises(ValueError, match='no page was truncated'):
        discover_audit_sources(gateway, result, _context(result), audit)
    assert len(gateway.calls) == 2
    assert audit['source_discovery']['status'] == 'failed'
    assert result.document == original


def test_no_unread_pages_records_only_physical_coverage_without_a_model_call():
    result, _ = fixture()
    class NoCall:
        def generate_structured(self, *args, **kwargs):
            raise AssertionError('Every source page is already available.')
    audit = {}
    expanded = discover_audit_sources(NoCall(), result, _context(result), audit)
    assert audit['source_discovery']['method'] == 'all_pages_already_present'
    assert expanded['source_discovery']['added_pages'] == []
    assert 'draft' not in audit and 'review' not in audit  # No assurance approval is manufactured.
    validate_audit_source_discovery(result, expanded, audit['source_discovery'])


def test_incomplete_physical_navigation_fails_without_model_admission():
    result = unread_case()
    result.document.pages.pop()
    audit, gateway = {}, SelectionGateway()
    with pytest.raises(ValueError, match='cannot silently omit pages'):
        discover_audit_sources(gateway, result, _context(result), audit)
    assert not gateway.calls and audit['source_discovery']['status'] == 'failed'


def test_privacy_error_never_falls_back_or_becomes_empty_source_selection():
    from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
    class BlockedGateway:
        calls = 0
        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            raise PrivacyViolationError('Local Only forbids a non-loopback endpoint')
    result = unread_case()
    audit, gateway = {}, BlockedGateway()
    with pytest.raises(PrivacyViolationError):
        discover_audit_sources(gateway, result, _context(result), audit)
    assert gateway.calls == 1 and audit['source_discovery']['status'] == 'failed'
    assert audit['source_discovery']['attempts'][0]['selection_output_attempts'][0]['status'] == 'privacy_blocked'
