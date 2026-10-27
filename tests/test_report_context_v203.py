"""Generic latest-period, companion-evidence and source-explanation regressions."""
import json

import pytest

from adaptive_document_agent.agent.brief_companion_context import companion_excerpts
from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview, meaning_validator
from adaptive_document_agent.agent.insight_generator import InsightGenerator, InsightList
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models import DocumentPage, Observation, PresentationTopicSelection, SourceEvidence
from adaptive_document_agent.models.executive_brief import BriefQuote, ExecutiveBrief, ExecutiveBriefItem
from tests.test_budget_output_v145 import gateway, response
from tests.test_executive_brief import result_for
from tests.test_insight_narrative_context import sample
from tests.test_topic_coverage_review import _fixture, _topic, _review
from tests.test_topic_review_recovery_v203 import verdict


@pytest.mark.parametrize('metric,counterpoint', [
    ('Output', 'Waste'), ('Satisfaction', 'Turnover intention'), ('Reported result', 'Adjusted result'),
])
def test_recent_and_counterpoint_decisions_survive_selection_and_compilation(metric, counterpoint):
    result, _, lookup, annual, interim, adverse = _fixture(metric, counterpoint)
    draft = PresentationTopicSelection(topics=[_topic(annual)])
    g, client = gateway([response(draft), response(verdict('history')),
        response(_review(annual, interim, adverse)), response(verdict('current', 'counterpoint'))])
    result.presentation_topics = PresentationTopicSelector(g).select(result)
    assert {sid for t in result.presentation_topics.topics for sid in t.series_ids} == {annual, interim, adverse}
    assert len(client.requests) == 4
    from adaptive_document_agent.agent.chart_planner import ChartPlanner
    from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
    from adaptive_document_agent.document_model import DocumentIndex
    result.charts = ChartPlanner().plan([], [], DocumentIndex(result.observations),
        requested_series=[lookup[sid] for sid in (annual, interim, adverse)], only_requested=True)
    plan = compile_topic_plan(result)
    assert {t.id for t in plan.themes} == {'history', 'current', 'counterpoint'}
    assert all(s.analytical_question for s in plan.slides if s.slide_type == 'analysis')
    assert all(set(c.observation_ids) <= {o.id for o in result.observations} for c in result.charts)
    # Different period bases remain separate; no artificial annual/interim growth.
    for chart in result.charts:
        members = [o for o in result.observations if o.id in chart.observation_ids]
        assert len({o.period_basis for o in members}) == 1


@pytest.mark.parametrize('metric,context', [
    ('Borrowings', 'Borrowings include both current and non-current balances.'),
    ('Participation', 'Participation excludes temporary staff; the weighted rate uses eligible staff.'),
    ('Energy demand', 'Energy demand under the stress scenario assumes continuous full-capacity operation.'),
])
def test_companion_source_reading_preserves_full_qualifications_without_metric_rules(metric, context):
    result = result_for([metric + ': reported values.', context, 'Unrelated narrative.'])
    result.observations = [Observation(id='a', metric_original=metric, raw_value='12', value=12, confidence=.9,
        evidence=[SourceEvidence(page=1, text=metric + ': reported values.',
                                 extraction_method='text', confidence=.9)])]
    original = result.model_dump()
    assert companion_excerpts(result, {1: result.document.pages[0].text}) == {2: context}
    assert result.model_dump() == original


def test_many_results_do_not_starve_adjacent_and_remote_explanations():
    document, item, calculation, insight = sample()
    explanation = 'The report attributes Service hours to revised routing.'
    document.pages[1].page_number = 12
    document.pages[1].text = explanation
    document.pages.append(DocumentPage(page_number=25, text='Service hours have a separate seasonal scope.'))
    results = [calculation.model_copy(update={'task_id': f'r{i}'}) for i in range(20)]
    seen = []

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            seen.extend(payload)
            return InsightList(insights=[])

    InsightGenerator(Gateway()).generate(results, [item], document=document)
    assert len(seen) == 20
    assert all(explanation in str(row['source_context']) for row in seen)
    assert all('seasonal scope' in str(row['source_context']) for row in seen)


def test_equal_label_overlap_does_not_prefer_longer_table_labels_over_prose():
    from adaptive_document_agent.agent.insight_source_context import _page_windows
    explanation = 'Service hours changed after revised routing. ' * 8
    table = '\n'.join('Service hours  ' + 'Product name 12345  ' * 12 for _ in range(8))
    windows = _page_windows(explanation + '\n\n' + table, len(explanation), ['service hours'])
    assert explanation.strip() in windows[0][1]


@pytest.mark.parametrize('fact,qualification', [
    ('Resources support the stated operating horizon.', 'The horizon assumes unchanged consumption and excludes new funding.'),
    ('The survey reports staff satisfaction.', 'Temporary staff are excluded from the survey population.'),
    ('The study reports a treatment outcome.', 'The study does not establish effects outside the observed follow-up.'),
])
def test_contextual_omission_rejects_a_literally_supported_claim_and_rechecks_the_whole_brief(fact, qualification):
    result = result_for([fact, qualification])
    item = ExecutiveBriefItem(label='Finding', text=fact, evidence=[BriefQuote(page=1, text=fact)])
    brief = ExecutiveBrief(items=[item])
    context = {'evidence_blocks': {'p1': {'page': 1, 'text': fact}, 'p2': {'page': 2, 'text': qualification}}}
    payloads = []

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            payload = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
            if schema is BriefClaimDirectionReview:
                return schema(items=[dict(index=row['index'], comparisons=[]) for row in payload])
            assert schema is BriefMeaningReview
            payloads.append(payload)
            available = payload[0]['available_report_context']
            assert available['evidence_blocks'] == context['evidence_blocks']
            included = any(i['text'] == qualification for i in available['current_brief']['items'])
            return BriefMeaningReview(items=[dict(index=row['index'], accepted=included,
                numeric_comparison=False, reason='Context preserved.' if included else
                'Missing qualification from p2 changes the interpretation.') for row in payload])

    validate = meaning_validator(Gateway(), result=result, source_context=context)
    assert 'p2' in str(validate(brief))
    qualified = brief.model_copy(deep=True)
    qualified.items.append(ExecutiveBriefItem(label='Scope', text=qualification,
        evidence=[BriefQuote(page=2, text=qualification)]))
    assert validate(qualified) == {}
    assert validate(brief)  # Removing the companion cannot borrow its approval.
    assert len(payloads) == 2


def test_topic_explanation_attaches_only_to_exact_visible_input_scope():
    from adaptive_document_agent.agent.topic_explanations import attach_topic_explanations
    from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
    from adaptive_document_agent.models import PipelineResult, DocumentProfile
    from adaptive_document_agent.agent.insight_generator import InsightGenerator
    from tests.test_insight_narrative_context import CapturingGateway
    document, item, calculation, insight = sample(explanation='The report attributes Service hours to revised routing.')
    item.validation_status = 'valid'
    result = PipelineResult(document=document, profile=DocumentProfile(), observations=[item],
        analysis_results=[calculation])
    result.insights = InsightGenerator(CapturingGateway(insight)).generate([calculation], [item], document=document)
    plan = PresentationPlanRecovery().fallback(result, validate=False)
    from adaptive_document_agent.models import PresentationSlide
    slide = PresentationSlide(id='question', slide_type='analysis', title='Service hours', section_title='Service hours',
        analytical_question='What explains service hours?', message='What explains service hours?',
        observation_ids=[item.id], source_pages=[10])
    plan.slides = [s for s in plan.slides if s.slide_type not in {'analysis', 'risks'}]
    plan.slides.insert(3, slide)
    attach_topic_explanations(plan, result)
    actual = next(s for s in plan.slides if s.id == 'question')
    assert actual.analytical_question == slide.analytical_question
    assert actual.bullets == [insight.narrative], result.validation_warnings
    assert 12 not in actual.source_pages and 11 in actual.source_pages
    assert actual.bullet_observation_ids == [[item.id]]
    # Identical wording/nearby source pages cannot link a different input.
    other = plan.model_copy(deep=True)
    target = next(s for s in other.slides if s.id == 'question')
    target.observation_ids = []
    target.insight_ids = []
    target.bullets = []
    target.bullet_observation_ids = []
    attach_topic_explanations(other, result)
    assert target.bullets == []
