"""Summary evidence survives tables, source scopes and failed model writing."""
import json

from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter, _selected_topic_pages, _table_evidence_guide
from adaptive_document_agent.models import (
    AnalysisResult, ChartPlan, Insight, Observation, PresentationPlan, PresentationSlide, SourceEvidence,
)
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.executive_brief import display_brief
from tests.test_executive_brief import gateway, payload, result_for


def fixture():
    result = result_for(['Operations FY2023 10 FY2024 20', 'Participation FY2023 70 FY2024 75'])
    for metric, page, numbers, unit in [('Output', 1, [10, 20], 'count'), ('Participation', 2, [70, 75], 'percent')]:
        for year, value in zip([2023, 2024], numbers):
            result.observations.append(Observation(id=f'{metric}-{year}', metric_original=metric,
                raw_value=str(value), value=value, unit=unit, period=f'FY{year}', period_type='fiscal_year', confidence=.99,
                evidence=[SourceEvidence(page=page, text=f'{metric} {value}', extraction_method='digital_table', confidence=.99)]))
    result.charts = [ChartPlan(id='chart', title='Output', chart_type='line', question='Movement',
        observation_ids=['Output-2023', 'Output-2024'])]
    result.presentation_plan = PresentationPlan(title='Review', slides=[
        PresentationSlide(id='output', slide_type='analysis', title='Output', section_id='output',
            chart_ids=['chart'], observation_ids=['Output-2023', 'Output-2024'], source_pages=[1]),
        PresentationSlide(id='participation', slide_type='analysis', title='Participation', section_id='participation',
            layout='table_plus_kpis', observation_ids=['Participation-2023', 'Participation-2024'], source_pages=[2]),
    ])
    return result


def test_fallback_covers_chart_and_table_selected_topics_without_mutating_values():
    result = fixture()
    original = result.model_dump_json()
    title, items = display_brief(result)
    assert title == 'Executive Summary'
    assert [item.title for item in items] == ['Output', 'Participation']
    assert items[0].text.count('Output:') == 1
    assert 'FY2023 70.0%' in items[1].text and 'FY2024 75.0%' in items[1].text
    assert items[1].pages == [2]
    assert result.model_dump_json() == original


def test_table_fallback_never_retrieves_unselected_or_conflicting_values():
    result = fixture()
    extra = result.observations[-1].model_copy(deep=True)
    extra.id = 'unselected'
    extra.value = 90
    result.observations.append(extra)
    assert '90' not in display_brief(result)[1][1].text
    result.presentation_plan.slides[1].observation_ids.append(extra.id)
    assert [item.title for item in display_brief(result)[1]] == ['Output']


def test_table_fallback_does_not_compare_annual_and_interim_periods():
    result = fixture()
    result.observations[-1].period = '6M2024'
    result.observations[-1].period_type = 'interim'
    result.observations[-1].period_basis = 'six_months'
    assert [item.title for item in display_brief(result)[1]] == ['Output']


def test_topic_retrieval_anchors_deduplicate_continued_slides():
    result = fixture()
    continued = result.presentation_plan.slides[0].model_copy(deep=True)
    continued.id = 'output-continued'
    continued.source_pages = [1, 3]
    result.presentation_plan.slides.insert(1, continued)
    assert _selected_topic_pages(result, {1, 2, 3}) == [('Output', [1, 3]), ('Participation', [2])]


def test_closing_representatives_follow_selected_topics_before_repeated_findings():
    from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery

    result = fixture()
    for i, metric in enumerate(['Output', 'Output', 'Output', 'Output', 'Participation']):
        ids = [f'{metric}-2023', f'{metric}-2024']
        evidence = next(item.evidence for item in result.observations if item.id == ids[0])
        result.analysis_results.append(AnalysisResult(task_id=f't{i}', title=metric,
            result={'value': 1}, input_observation_ids=ids, evidence=evidence))
        result.insights.append(Insight(id=f'i{i}', title=metric, narrative='A source-bound finding.',
            kind='interpretation',
            implication=f'{metric} finding {chr(65+i)} remains relevant to the reported performance.',
            result_ids=[f't{i}'], evidence=evidence, importance=1-i/10))
    summary = PresentationSlide(id='summary', slide_type='executive_summary', title='Summary')
    closing = PresentationPlanRecovery._risks_slide(result, summary, topic_observation_groups=[
        {'Output-2023', 'Output-2024'}, {'Participation-2023', 'Participation-2024'}])
    assert closing.insight_ids == ['i0', 'i4', 'i1', 'i2']
    assert closing.bullet_observation_ids[1] == ['Participation-2023', 'Participation-2024']


def test_brief_payload_exposes_limits_and_only_literal_ordered_table_rows():
    source = 'FY2023 FY2024\nUSD thousands\nCost (1,475) (2,300)\nOutput 10 20'
    result = result_for([source])
    result.document.pages[0].tables = [ExtractedTable(table_id='t', page=1, headers=['Metric', 'FY2023', 'FY2024'],
        raw_header_lines=['FY2023 FY2024', 'USD thousands', 'invented heading'],
        rows=[TableRow(page=1, cells=['Cost', '(1,475)', '(2,300)'], alignment_status='resolved'),
              TableRow(page=1, cells=['Output', '20', '10'], alignment_status='resolved'),
              TableRow(page=1, cells=['Output', '10', '20'], alignment_status='ambiguous')])]
    guide = _table_evidence_guide(result, {1: source})
    assert guide[0]['ordered_source_rows'] == [['Cost', '(1,475)', '(2,300)']]
    assert guide[0]['literal_header_lines'] == ['FY2023 FY2024', 'USD thousands']
    g, client = gateway([payload('Output 10 20')])
    ExecutiveBriefWriter(g).generate(result)
    data = json.loads(client.calls[0][1]['content'].split('<UNTRUSTED_DOCUMENT_CONTENT>\n')[1].split('\n</UNTRUSTED_DOCUMENT_CONTENT>')[0])
    assert data['output_limits']['text_characters'] == 550
    assert data['source_table_guide'] == guide
