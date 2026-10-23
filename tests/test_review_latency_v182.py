"""Avoid repeat reasoning without changing evidence or semantic approval gates."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent import report_audit_scope as audit_scope
from adaptive_document_agent.agent import report_audit_review_output as audit_output
from adaptive_document_agent.agent import source_integration_review as sources
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_budget_output_v145 import response
from tests.test_report_audit_batches_v174 import BatchGateway, many_targets
from tests.test_source_integration_v166 import Gateway, fixture


class CapacityGateway:
    """Synthetic output needs; no real model calls or wall-time claims."""
    def __init__(self, delegate, needs):
        self.delegate, self.needs, self.requests = delegate, needs, []

    def generate_structured(self, messages, schema, **kwargs):
        self.requests.append((schema.__name__, deepcopy(messages), kwargs))
        if kwargs['max_tokens'] < self.needs[schema.__name__]:
            raise LLMStructuredOutputError('Reasoning and JSON exceed capacity',
                                           response=response('', finish='length'))
        return self.delegate.generate_structured(messages, schema, **kwargs)


@pytest.mark.parametrize('accepted', [True, False])
def test_audit_capacity_eliminates_initial_replays_with_identical_review_outcome(monkeypatch, accepted):
    result, binding = many_targets(3)
    context = audit_scope._context(result)
    original = deepcopy(context)

    def run():
        gateway = CapacityGateway(BatchGateway(binding, reject_group=None if accepted else 0),
                                  {'AuditScopeDraft': 17006, 'AuditScopeReview': 16283})
        record = {'attempts': []}
        if accepted:
            audit_scope._review_batch(gateway, context, record)
        else:
            with pytest.raises(ValueError, match='correction budget exhausted'):
                audit_scope._review_batch(gateway, context, record)
        return gateway, record

    with monkeypatch.context() as old:
        old.setattr(audit_scope, 'AUDIT_DRAFT_TOKEN_LIMITS', (12000, 20000))
        old.setattr(audit_output, 'AUDIT_REVIEW_TOKEN_LIMITS', (8192, 16384))
        before, old_record = run()
    after, new_record = run()
    assert len(after.requests) * 2 == len(before.requests)
    assert context == original
    assert [r[:2] for r in before.requests[1::2]] == [r[:2] for r in after.requests]
    assert len(new_record['attempts']) == len(old_record['attempts'])
    for old_attempt, new_attempt in zip(old_record['attempts'], new_record['attempts']):
        assert new_attempt['draft'] == old_attempt['draft']
        assert new_attempt.get('review') == old_attempt.get('review')
    assert (new_record.get('status') == 'complete') == accepted


@pytest.mark.parametrize('accepted', [True, False])
def test_supplementary_capacity_saves_a_request_without_bypassing_rejection(monkeypatch, accepted):
    original, constraint = fixture()

    def run():
        result = original.model_copy(deep=True)
        gateway = CapacityGateway(Gateway(constraint, accept=accepted),
                                  {'SourceIntegrationDraft': 15782, 'SourceIntegrationReview': 6237})
        result.executive_brief = sources.review_supplementary_sources(
            gateway, result, result.executive_brief)
        return gateway, result

    with monkeypatch.context() as old:
        old.setattr(sources, 'SOURCE_OUTPUT_TOKEN_LIMITS', (8192, 16384))
        before, old_result = run()
    after, new_result = run()
    assert len(before.requests) == (3 if accepted else 6)
    assert len(after.requests) == (2 if accepted else 4)
    assert new_result.executive_brief == old_result.executive_brief
    assert new_result.document == old_result.document == original.document
    assert [r[:2] for i, r in enumerate(before.requests) if i % 3] == [r[:2] for r in after.requests]
    assert bool(sources.resolved_source_check_ids(new_result, new_result.executive_brief)) == accepted
    if accepted:
        new_audit = json.loads(new_result.validation_warnings[-1].message)
        old_audit = json.loads(old_result.validation_warnings[-1].message)
        assert new_audit['draft'] == old_audit['draft']
        assert new_audit['review'] == old_audit['review']
    else:
        assert new_result.executive_brief == original.executive_brief
