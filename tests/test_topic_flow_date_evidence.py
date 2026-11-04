"""An explicitly dated topic interval must belong to each selected source cell."""
import pytest

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models import Observation, PresentationTopic, PresentationTopicSelection, SourceEvidence
from tests.test_brief_targeted_contract_v147 import geometry_alias_case


def case():
    result, _ = geometry_alias_case()
    table = result.document.pages[0].tables[0]
    observations = [Observation(id=f'o{column}', metric_original='Programme fees',
        raw_value=table.rows[0].cells[column], period=table.column_periods[column], confidence=1,
        table_id=table.table_id, row_id=0, column_id=column, evidence=[SourceEvidence(page=1,
        table_id=table.table_id, row_label='Programme fees', text=table.rows[0].cells[column],
        extraction_method='table', confidence=1)]) for column in (2, 3)]
    topic = PresentationTopic(id='fees', title='Fees', rationale='Compare the matching reporting periods.',
        takeaway='Fees changed.', question='How did fees change for the nine months ended November 15, 2023 and 2024?',
        series_ids=['fees'])
    return result, observations, PresentationTopicSelection(topics=[topic])


def test_source_bound_nonstandard_closing_date_accepts_coordinated_years_without_rewriting_copy():
    result, rows, selection = case()
    before = selection.model_dump_json()
    PresentationTopicSelector._validate(selection, {'fees':rows}, result=result)
    assert selection.model_dump_json() == before


@pytest.mark.parametrize('source_day', ['15', '14'])
def test_versioned_planner_reviews_and_compiles_a_date_only_with_current_source_geometry(source_day):
    from adaptive_document_agent.agent.presentation_planner import PresentationPlanner
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    from adaptive_document_agent.agent.topic_evidence_review import TopicEvidenceReview

    result, rows, selection = case()
    for row in rows:
        row.value = float(row.raw_value)
        row.period_type = 'interim_flow'
        row.period_basis = '9M'
    result.observations = rows
    result.pipeline_version = 'test'
    result.presentation_topics = selection
    page = result.document.pages[0]
    table = page.tables[0]
    table.raw_header_lines = [line.replace('November 15', f'November {source_day}') for line in table.raw_header_lines]
    page.text = page.text.replace('November 15', f'November {source_day}')
    for line in page.text_blocks[0]['lines']:
        line['text'] = line['text'].replace('November 15', f'November {source_day}')
    series_id, = series_directory(result)[1]
    topic = selection.topics[0]
    topic.series_ids = [series_id]
    calls = []

    class Reviewer:
        def generate_structured(self, messages, response_model, **kwargs):
            assert response_model is TopicEvidenceReview
            assert topic.question in messages[-1]['content']
            calls.append(response_model)
            return response_model(decisions=[dict(topic_id=topic.id, supported=True,
                reason='The selected fee cells belong to both nine-month columns.')])

    if source_day == '14':
        with pytest.raises(ValueError, match='unsupported numeric claims'):
            PresentationPlanner(Reviewer()).plan(result)
        assert not calls
    else:
        plan = PresentationPlanner(Reviewer()).plan(result)
        slide, = [slide for slide in plan.slides if slide.slide_type == 'analysis']
        assert slide.analytical_question == topic.question
        assert set(slide.observation_ids) == {row.id for row in rows}
        assert calls == [TopicEvidenceReview]


@pytest.mark.parametrize('fault', ['wrong_month','wrong_day','annual_date','wrong_duration','extra_year',
    'wrong_table','wrong_column','wrong_value','wrong_row','unowned_peer','no_geometry','unrelated_date',
    'fiscal_year','conflicting_metadata','split_fields'])
def test_explicit_date_cannot_borrow_an_annual_or_unowned_header(fault):
    result, rows, selection = case()
    topic = selection.topics[0]
    if fault in {'wrong_month','wrong_day','annual_date','wrong_duration','extra_year'}:
        old, new = {'wrong_month':('November','October'), 'wrong_day':('15','14'),
            'annual_date':('November 15','December 31'), 'wrong_duration':('nine','six'),
            'extra_year':('2023 and 2024','2022 and 2024')}[fault]
        topic.question = topic.question.replace(old, new)
    elif fault == 'wrong_table':
        rows[0].evidence[0].table_id = 'foreign'
    elif fault == 'wrong_column':
        rows[0].column_id = 1
    elif fault == 'wrong_value':
        rows[0].raw_value = '500'
    elif fault == 'wrong_row':
        rows[0].evidence[0].row_label = 'Other fees'
    elif fault == 'unowned_peer':
        rows.append(rows[0].model_copy(update={'id':'other','column_id':None}))
    elif fault == 'no_geometry':
        result.document.pages[0].text_blocks = []
    elif fault == 'fiscal_year':
        rows[0].period_type = 'fiscal_year'
    elif fault == 'conflicting_metadata':
        rows[0].period_end = '2023-12-31'
    elif fault == 'split_fields':
        topic.question = 'How did fees change in the nine months ended'
        topic.rationale = 'November 15, 2023 and 2024?'
    else:
        topic.question += ' Did it launch on November 15, 2024?'
    with pytest.raises(ValueError, match='unsupported numeric claims'):
        PresentationTopicSelector._validate(selection, {'fees':rows}, result=result)


def test_two_possible_closings_for_a_duration_and_year_cannot_grant_either_date(monkeypatch):
    from adaptive_document_agent.agent import brief_period_geometry
    result, rows, selection = case()
    original = brief_period_geometry.table_flow_closings
    monkeypatch.setattr(brief_period_geometry, 'table_flow_closings',
        lambda page, table: original(page, table) | {(9, '2023-10-15')})
    with pytest.raises(ValueError, match='unsupported numeric claims'):
        PresentationTopicSelector._validate(selection, {'fees':rows}, result=result)
