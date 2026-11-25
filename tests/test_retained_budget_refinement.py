from copy import deepcopy
import json

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
    from pptx import Presentation
    from adaptive_document_agent.agent import presentation_budget_refinement as native
    import adaptive_document_agent.agent.retained_budget_refinement as module
    def measure(result):
        slides = [s for s in result.presentation_plan.slides if s.slide_type == 'analysis']
        result.presentation_export_trace = [dict(planned_slide_id=s.id, slide_numbers=[n + 2])
                                            for n, s in enumerate(slides)]
        deck = Presentation()
        for _ in range(1 + len(slides)):
            deck.slides.add_slide(deck.slide_layouts[6])
        return deck, dict(body=1 + len(slides), analysis=len(slides), introduction=0)
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


def test_retained_budget_reports_actual_distinct_chart_pages_and_original_target(monkeypatch):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    from adaptive_document_agent.agent import presentation_budget_refinement as native
    result = prepared()
    # A different chart target would change the model's choice, never this measurement.
    request = 'Retain one analytical chart page within the report cap.'
    result.profile.report_requirements.original_request = request
    ids = [s.id for s in result.presentation_plan.slides if s.slide_type == 'analysis']
    deck = Presentation()
    for number in range(1, 5):
        page = deck.slides.add_slide(deck.slide_layouts[6])
        for _ in range({1: 1, 2: 2}.get(number, 0)):
            data = CategoryChartData()
            data.categories = ['Period']
            data.add_series('Metric', [1])
            page.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1),
                                  Inches(2), Inches(2), data)

    native_fixture(monkeypatch)
    projected_measure = native.measure
    def measure(candidate):
        if candidate is not result:
            return projected_measure(candidate)
        result.presentation_export_trace = [
            dict(planned_slide_id=ids[0], slide_numbers=[2]),
            dict(planned_slide_id=ids[0], slide_numbers=[2, 3]),
            dict(planned_slide_id=ids[1], slide_numbers=[4])]
        return deck, dict(body=4, analysis=3, introduction=0)
    monkeypatch.setattr(native, 'measure', measure)
    llm = gateway([proposal(result)])
    assert refine_retained_budget(llm, result)
    prompt = llm.client.calls[0]
    context = json.loads(prompt[-1]['content'].split('<UNTRUSTED_DOCUMENT_CONTENT>', 1)[1]
                         .split('</UNTRUSTED_DOCUMENT_CONTENT>', 1)[0])
    assert context['requirements']['original_request'] == request
    assert context['measured_counts']['analysis'] == 3
    assert context['native_chart_slide_numbers_outside_candidates'] == [1]
    first, second = context['candidates']
    assert (first['physical_slides'], first['native_chart_pages']) == (2, 1)
    assert (first['physical_slide_numbers'], first['native_chart_slide_numbers']) == ([2, 3], [2])
    assert (second['physical_slides'], second['native_chart_pages']) == (1, 0)


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


def test_feasible_chart_combinations_count_distinct_physical_pages_and_all_caps():
    from adaptive_document_agent.agent.retained_budget_refinement import measured_chart_options
    def finding(iid, pages, charts):
        return dict(insight_id=iid, physical_slide_numbers=pages, native_chart_slide_numbers=charts)
    candidates = [finding('a', [3, 4], [3]), finding('b', [5], [5]),
                  finding('c', [6, 7], [6]), finding('d', [6], [6])]
    options = measured_chart_options(candidates, [(set(range(1, 9)), 6), ({3, 4, 5, 6, 7}, 3)])
    assert options['maximum_analysis_chart_pages'] == 2
    assert {tuple(row['insight_ids']) for row in options['combinations_at_maximum']} == {
        ('a', 'b'), ('a', 'd'), ('b', 'c'), ('b', 'd'), ('b', 'c', 'd')}
