"""Measured scope changes stay model-owned; identical failed native inputs need no rebuild."""
import json

import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.models import DocumentPage
from tests.test_physical_budget_refinement_v130 import measurement, source
from tests.test_budget_output_v145 import failure_audit


def test_known_noop_proposals_retain_all_decisions_and_reuse_only_the_failed_native_cost(monkeypatch):
    result, _, original, draft = source()
    measurements, calls = [], []
    def measured(current):
        measurements.append(current.presentation_topics.model_dump())
        deck, counts = measurement(current, 21, 10)
        current.presentation_export_trace[0]['topic_id'] = current.presentation_topics.topics[0].id
        counts['topic_pages'] = [dict(topic_id=topic.id, physical_slides=cost)
                                for topic, cost in zip(original.topics, (4, 3, 3))]
        return deck, counts
    monkeypatch.setattr(budget, 'measure', measured)
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            assert schema is budget.PhysicalBudgetSelection
            assert next(iter(schema.model_json_schema()['properties'])) == 'decisions'
            if len(calls) == 1:
                context = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                assert context['required_physical_change']['measured_native_groups'] == context['measured_costs']['native_groups']
                assert 'one omitted series equals one saved page' in messages[0]['content']
                assert 'not claim-by-claim display proof' in context['measured_costs']['native_groups'][0]['mapping_basis']
            if len(calls) == 2:
                feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                action = feedback['required_physical_change']
                assert action['current_analysis_slides'] == 10
                assert action['analysis_capacity_with_current_overhead'] == 9
                assert action['required_analysis_slide_reduction'] == 1
                assert action['report_constraints'][0]['measured_slides'] == 21
                assert action['report_constraints'][0]['maximum_slides'] == 20
                assert action['measured_original_topic_costs'][0]['physical_slides'] == 4
                assert action['measured_native_groups'] == feedback['projected_counts']['native_groups']
                assert 'Cross-topic evidence unions are not supported' in action['unsupported_action']
                assert 'Rewording titles' in action['copy_only_warning']
                assert 'no omissions' in action['authority']
            value = draft.model_copy(deep=True)
            # Different model-authored reasons are still retained; they cannot
            # change the native inputs or grant an acceptance.
            if len(calls) == 2:
                value.decisions[0].reason = 'The unchanged chosen scope still requires this independently supported comparison.'
            return value
    with pytest.raises(ValueError, match='known failed physical cost'):
        budget.refine_presentation_budget(Client(), result)
    assert calls == ['PhysicalBudgetSelection', 'PhysicalBudgetSelection']
    assert len(measurements) == 2  # Initial deck and first proposal, no third build.
    assert result.presentation_topics == original
    first, second = failure_audit(result)['attempts']
    assert first['status'] == second['status'] == 'rejected'
    assert first['projected_counts'] == second['projected_counts']
    assert second['reused_failed_native_projection']['measured_attempt'] == 1
    assert second['reused_failed_native_projection']['semantic_approval'] is False
    assert first['proposal']['decisions'][0]['reason'] != second['proposal']['decisions'][0]['reason']
    assert all('independent_review' not in record and 'review_output_attempts' not in record for record in (first, second))


def test_same_series_with_changed_topic_copy_is_measured_again_instead_of_reusing_a_failure(monkeypatch):
    result, _, _, draft = source()
    counts = []
    def measured(current):
        counts.append(current.presentation_topics.model_dump())
        return measurement(current, 21, 10)
    monkeypatch.setattr(budget, 'measure', measured)
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            value = draft.model_copy(deep=True)
            if self.calls == 2:
                value.topics[0].title = 'Supported reported scope'
            return value
    with pytest.raises(ValueError, match='maximum is 20'):
        budget.refine_presentation_budget(Client(), result)
    assert len(counts) == 3
    assert all('reused_failed_native_projection' not in record for record in failure_audit(result)['attempts'])


@pytest.mark.parametrize('changed', ['topic_copy', 'plan_copy', 'source_value', 'document', 'template'])
def test_native_identity_requires_full_copy_evidence_layout_and_template_equivalence(monkeypatch, tmp_path, changed):
    result, _, _, _ = source()
    from adaptive_document_agent.services import pptx_export
    template = tmp_path / 'template-reference.bin'
    template.write_bytes(b'Original template revision')
    monkeypatch.setattr(pptx_export, '_resolve_template_path', lambda: template)
    before = budget._native_projection_identity(result)
    if changed == 'topic_copy': result.presentation_topics.topics[0].rationale += ' Additional source scope.'
    elif changed == 'plan_copy': result.presentation_plan.title += ' Expanded context'
    elif changed == 'source_value': result.observations[0].raw_value = 'Different retained source value'
    elif changed == 'document': result.document.pages.append(DocumentPage(page_number=1, text='Additional literal evidence.'))
    else: template.write_bytes(b'A different longer template revision')
    assert budget._native_projection_identity(result) != before
