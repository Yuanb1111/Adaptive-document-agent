from copy import deepcopy

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_budget_refinement import (
    RetainedPhysicalBudgetSelection, project_retained_budget, refine_retained_budget,
)
from adaptive_document_agent.models.customization import ReportRequirement, ReportRequirements
from adaptive_document_agent.services.pipeline_completion import require_topic_coverage
from tests.test_retained_analysis_v216 import _linked_result, gateway, selection


def prepared():
    result = _linked_result()
    result.insights.append(result.insights[0].model_copy(update={'id': 'other-finding'}))
    result.profile.report_requirements = ReportRequirements(items=[ReportRequirement(id='body',
        kind='slide_limit', request_quote='Two body slides', description='Synthetic physical cap',
        max_slides=2, slide_scope='body')])
    retained.select_retained_analysis(gateway([selection(result)]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    return result


def proposal(result, *, keep_all=False):
    ids = retained.selected_record(result)['selection']['ordered_insight_ids']
    return dict(decisions=[dict(insight_id=iid, include=keep_all or n == 0,
        reason='Preserve the primary view; the secondary view has lower audience priority.')
        for n, iid in enumerate(ids)])


def native_fixture(monkeypatch):
    from adaptive_document_agent.agent import presentation_budget_refinement as native
    import adaptive_document_agent.agent.retained_budget_refinement as module
    def measure(result):
        slides = [s for s in result.presentation_plan.slides if s.slide_type == 'analysis']
        result.presentation_export_trace = [dict(planned_slide_id=s.id, slide_numbers=[n + 2])
                                            for n, s in enumerate(slides)]
        return object(), dict(body=1 + len(slides), analysis=len(slides), introduction=0)
    def require(_deck, result):
        if sum(s.slide_type == 'analysis' for s in result.presentation_plan.slides) > 1:
            raise ValueError('Native body has three slides; maximum is two.')
    monkeypatch.setattr(native, 'measure', measure)
    monkeypatch.setattr(module, 'require_exported_budgets', require)


def test_model_owned_native_reduction_preserves_all_source_and_kept_copy_and_needs_final_review(monkeypatch):
    result = prepared()
    before = result.model_dump(include={'document', 'observations', 'analysis_plan', 'analysis_results', 'charts'})
    original_plan = result.presentation_plan.model_copy(deep=True)
    native_fixture(monkeypatch)
    llm = gateway([proposal(result)])
    assert refine_retained_budget(llm, result)
    assert result.model_dump(include=set(before)) == before
    assert result.presentation_plan.company == original_plan.company
    kept = [s for s in result.presentation_plan.slides if s.slide_type == 'analysis']
    assert kept == [s for s in original_plan.slides if s.slide_type == 'analysis'][:1]
    assert len(retained.selected_record(result)['selection']['ordered_insight_ids']) == 1
    with pytest.raises(ValueError, match='Retained-analysis evidence'):
        require_topic_coverage(result)


def test_two_unfitting_proposals_never_truncate_or_apply_a_selection(monkeypatch):
    result = prepared()
    before = deepcopy(retained.selected_record(result))
    plan = result.presentation_plan.model_copy(deep=True)
    native_fixture(monkeypatch)
    llm = gateway([proposal(result, keep_all=True)] * 2)
    with pytest.raises(ValueError, match='did not satisfy'):
        refine_retained_budget(llm, result)
    assert retained.selected_record(result) == before
    assert result.presentation_plan == plan
    assert len(llm.client.calls) == 2


def test_duplicate_or_unknown_budget_decisions_cannot_change_retained_inputs():
    result = prepared()
    original = result.model_dump_json()
    value = proposal(result)
    value['decisions'][1]['insight_id'] = value['decisions'][0]['insight_id']
    with pytest.raises(ValueError, match='exactly once'):
        project_retained_budget(result, RetainedPhysicalBudgetSelection.model_validate(value), {'body': 3})
    assert result.model_dump_json() == original
