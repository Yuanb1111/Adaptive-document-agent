"""Review explanations have bounded capacity; known geometry fails before paid review."""
import json

import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent.presentation_budget_output import REVIEW_TOKEN_LIMITS, complete_budget_output
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_budget_output_v145 import failure_audit, gateway, prepared_refinement, response
from tests.test_physical_budget_refinement_v130 import measurement, source


@pytest.mark.parametrize('accepted', [True, False])
@pytest.mark.parametrize('reason_length', [2102, 2134])
def test_complete_nontruncated_long_review_reason_is_preserved_with_its_actual_verdict(accepted, reason_length):
    # The retained failure had a 2,134-character full JSON body and 2,102-char
    # reason. This generic fixture exercises that exact transport size too.
    value = dict(accepted=accepted, reason='A' * reason_length)
    text = json.dumps(value)
    if accepted and reason_length == 2102:
        assert len(text) == 2134
    llm, client = gateway([response(text, finish='stop')])
    record = {}
    verdict = complete_budget_output(llm, [], budget.PhysicalBudgetReview, record,
        audit_key='review_output_attempts', token_limits=REVIEW_TOKEN_LIMITS)
    assert verdict.model_dump() == value
    assert len(client.requests) == 1 and llm.usage[0]['status'] == 'success'
    assert record['review_output_attempts'][0]['status'] == 'response_received'
    assert record['review_output_attempts'][0]['capacity_retry'] is False


def test_over_capacity_complete_review_is_terminal_without_format_or_semantic_retry(monkeypatch):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    maximum = budget.PhysicalBudgetReview.model_json_schema()['properties']['reason']['maxLength']
    assert maximum == 8000
    invalid = json.dumps(dict(accepted=True, reason='A' * (maximum+1)))
    llm, client = gateway([response(draft), response(invalid, finish='stop')])
    with pytest.raises(LLMStructuredOutputError, match='schema validation'):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 2 and not brief_calls
    assert result.presentation_topics == original
    audit = failure_audit(result)
    assert len(audit['attempts']) == 1
    record = audit['attempts'][0]
    assert record['projected_budget_gate']['native_gate_passed'] is True
    assert 'independent_review' not in record
    failed, = record['review_output_attempts']
    assert failed['raw_response'] == invalid and failed['status'] == 'invalid_format'
    assert failed['capacity_retry'] is False


def test_unchanged_over_budget_first_proposal_uses_second_proposal_before_fresh_review(monkeypatch):
    result, _, original, fitting = source()
    unchanged = budget.PhysicalBudgetSelection(topics=original.topics, decisions=[dict(
        series_id=series_id, include=True, reason='This comparison contributes supported audience context.')
        for topic in original.topics for series_id in topic.series_ids])
    events, calls = [], []
    def measured(current):
        count = len(current.presentation_topics.topics)
        events.append('measure:'+str(count))
        return measurement(current, 23 if count == 3 else 18, 12 if count == 3 else 8)
    monkeypatch.setattr(budget, 'measure', measured)
    from adaptive_document_agent.agent import executive_brief
    def briefing(self, current):
        events.append('brief')
        return None
    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', briefing)
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            if schema is budget.PhysicalBudgetSelection:
                events.append('selection')
                if len(calls) == 1:
                    return unchanged
                failed = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                assert failed['projected_counts']['body'] == 23
                assert failed['projected_budget_gate'] == dict(scoped_slides=23,
                    reserved_conclusion_pages=0, maximum_slides=20, over_budget_by=3, native_gate_passed=False)
                assert failed['projected_budget_allocation']['effective_analysis_capacity'] == 9
                assert 'independent_review' not in failed
                return fitting
            events.append('review')
            assert events[-2] == 'measure:2'
            assert result.presentation_topics == original
            return schema(accepted=True, reason='The recent reversal and adverse comparison remain source-faithful.')
    assert budget.refine_presentation_budget(Client(), result)
    assert calls == ['PhysicalBudgetSelection', 'PhysicalBudgetSelection', 'PhysicalBudgetReview']
    assert events == ['measure:3', 'selection', 'measure:3', 'selection', 'measure:2', 'review', 'brief', 'measure:2']
    audit = json.loads(next(issue.message for issue in result.validation_warnings
                           if issue.code == 'presentation_physical_budget_review'))
    first, final = audit['attempts']
    assert first['status'] == 'rejected' and 'review_output_attempts' not in first
    assert final['status'] == 'accepted' and final['independent_review']['accepted'] is True


def test_projected_boundary_without_conclusion_tags_still_requires_fresh_review_and_final_measure(monkeypatch):
    result, _, draft, brief_calls = prepared_refinement(monkeypatch)
    result.executive_brief = None
    measured_counts = []
    def measured(current):
        total = 23 if len(current.presentation_topics.topics) == 3 else 20
        measured_counts.append(total)
        deck, counts = measurement(current, total, 12 if total == 23 else 8)
        # Fallback summary/risk pages are already counted. The absence of
        # final-brief tags cannot justify adding hypothetical pages to them.
        for slide in deck.slides:
            slide.element.cSld.attrib.pop('name', None)
        return deck, counts
    monkeypatch.setattr(budget, 'measure', measured)
    verdict = budget.PhysicalBudgetReview(accepted=True, reason='The retained evidence and omission reasons are source-faithful.')
    llm, client = gateway([response(draft), response(verdict)])
    assert budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 2 and len(brief_calls) == 1
    assert measured_counts == [23, 20, 20]
    audit = json.loads(next(issue.message for issue in result.validation_warnings
                           if issue.code == 'presentation_physical_budget_review'))
    record, = audit['attempts']
    assert record['projected_budget_gate'] == dict(scoped_slides=20,
        reserved_conclusion_pages=0, maximum_slides=20, over_budget_by=0, native_gate_passed=True)
    assert record['independent_review']['accepted'] and record['final_counts']['body'] == 20


@pytest.mark.parametrize('projected_total', [18, 20])
def test_final_brief_geometry_still_cannot_exceed_the_native_budget_after_review(monkeypatch, projected_total):
    result, original, draft, brief_calls = prepared_refinement(monkeypatch)
    measurements = []
    def measured(current):
        # Each proposal fits before fresh review, then its new brief expands.
        index = len(measurements)
        total = 23 if index == 0 else projected_total if index % 2 else 21
        measurements.append(total)
        return measurement(current, total, 12 if index == 0 else 8)
    monkeypatch.setattr(budget, 'measure', measured)
    verdict = budget.PhysicalBudgetReview(accepted=True, reason='Source meaning and omission decisions are accepted.')
    llm, client = gateway([response(draft), response(verdict)] * 2)
    with pytest.raises(ValueError, match='physical slides'):
        budget.refine_presentation_budget(llm, result)
    assert len(client.requests) == 4 and len(brief_calls) == 2
    assert measurements == [23, projected_total, 21, projected_total, 21]
    assert result.presentation_topics == original
    assert all(record['independent_review']['accepted'] and record['final_counts']['body'] == 21
               for record in failure_audit(result)['attempts'])
