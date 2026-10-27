"""Rejected candidate review remains available to the one budget correction."""
import json

import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent import topic_evidence_review
from adaptive_document_agent.models import ValidationIssue
from tests.test_physical_budget_refinement_v130 import source, measurement


@pytest.mark.parametrize('raises', [False, True])
def test_budget_correction_receives_rejected_candidate_source_review(monkeypatch, raises):
    result, _, original, draft = source()
    result.pipeline_version = 'test-version'
    raw = [o.model_dump() for o in result.observations]
    monkeypatch.setattr(budget, 'measure', lambda r: measurement(r, 23, 12))
    reason = 'The proposed rate uses a different denominator from its selected row.'
    def reject(selection, lookup, candidate, gateway, validate, **kwargs):
        assert kwargs['allow_correction'] is False
        candidate.validation_warnings.append(ValidationIssue(code='presentation_topic_evidence_review',
            stage='presentation', severity='warning', message=json.dumps(dict(
                decisions=[dict(topic_id=selection.topics[0].id, supported=False, reason=reason)]))))
        if raises:
            raise ValueError('Source review could not accept the topic.')
        return selection.model_copy(update={'topics': selection.topics[1:]})
    monkeypatch.setattr(topic_evidence_review, 'review_topic_evidence', reject)
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert schema is budget.PhysicalBudgetSelection
            if self.calls == 2:
                assert reason in messages[-2]['content']
                assert messages[-2]['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>')
            return draft
    client = Client()
    with pytest.raises(ValueError, match='refinement exhausted'):
        budget.refine_presentation_budget(client, result)
    assert client.calls == 2
    assert result.presentation_topics == original
    assert [o.model_dump() for o in result.observations] == raw
    audit = json.loads(result.validation_warnings[-1].message)
    assert all(reason in str(attempt['source_semantic_audits']) for attempt in audit['attempts'])
