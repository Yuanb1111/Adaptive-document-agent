"""Page-cost feedback keeps model selection bounded without silent pruning."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.audit_discovery_budget import AuditDiscoveryBudgetError
from adaptive_document_agent.agent.report_audit_scope import _context
from adaptive_document_agent.agent.report_audit_source_discovery import (
    discover_audit_sources, validate_audit_source_discovery,
)
from tests.test_audit_source_format_correction_v177 import case
from tests.test_budget_output_v145 import gateway, response


@pytest.mark.parametrize('corrected', [False, True])
def test_exact_page_cost_feedback_can_repair_once_without_trimming_sources(corrected):
    result, _, oversized = case()
    result.document.pages[7].text += 'Full unread evidence. ' * 7500
    base = _context(result)
    original = deepcopy((result, base))
    smaller = oversized.model_copy(deep=True)
    smaller.ranges[0].start_page = 9
    smaller.ranges[0].end_page = 9
    llm, client = gateway([response(oversized), response(smaller if corrected else oversized)])
    audit = {}
    if corrected:
        expanded = discover_audit_sources(llm, result, base, audit)
        assert expanded['source_discovery']['added_pages'] == [9]
        assert expanded['source_pages'][-1]['text'] == result.document.pages[8].text
        validate_audit_source_discovery(result, expanded, audit['source_discovery'])
    else:
        with pytest.raises(AuditDiscoveryBudgetError):
            discover_audit_sources(llm, result, base, audit)
        assert audit['source_discovery']['status'] == 'failed'
        assert audit['source_discovery']['attempts'][-1]['correction_budget_exhausted']
    assert len(client.requests) == 2
    entry = audit['source_discovery']['attempts'][0]
    details = entry['correction_feedback']['source_budget']
    assert details['limit'] == 150_000
    assert details['excess_characters'] == details['proposed_batch_characters'] - details['limit'] > 0
    assert details['proposed_batch_characters'] == (details['base_batch_characters']
        + details['added_page_characters'] + details['selection_metadata_characters'])
    assert [p['page'] for p in details['selected_full_pages']] == [8, 9]
    assert details['added_page_characters'] == sum(p['serialized_characters'] for p in details['selected_full_pages'])
    feedback = client.requests[1][0][-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]
    assert json.loads(feedback)['source_budget'] == details
    assert entry['selection'] == oversized.model_dump(mode='json')
    assert 'review' not in audit and 'ledger' not in audit
    assert (result, base) == original
