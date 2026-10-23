"""Chapter/index scope follows all shown periods and the authored topic names."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import ChartPlan, PresentationSlide, PresentationTopicSelection
from adaptive_document_agent.services.presentation_data_index import index_entries, render_data_index
from adaptive_document_agent.services.presentation_section_titles import source_scoped_heading
from adaptive_document_agent.services.slide_compositor import render_composed_slide, validate_composed_geometry
from tests.test_p0_composition import observation, result_for
from tests.test_presentation_brief import blank_deck
from tests.test_topic_coverage_review import _topic


@pytest.mark.parametrize(('title', 'periods', 'expected'), [
    ('Capacity, FY2021 to FY2023', ['FY2021', 'FY2022', 'FY2023'], 'Capacity, FY2021 to FY2023'),
    ('Capacity, FY2021 to FY2023', ['FY2022', 'FY2023'], 'Capacity'),
    ('Capacity, FY2022–FY2023', ['FY2021', 'FY2022', 'FY2023'], 'Capacity'),
    ('Capacity, FY2021-FY2023', ['FY2021', 'FY2022', 'FY2023'], 'Capacity, FY2021-FY2023'),
    ('Capacity, FY2021 and FY2023', ['FY2021', 'FY2022', 'FY2023'], 'Capacity'),
    ('Capacity, FY2021 and FY2023', ['FY2021'], 'Capacity'),
    ('Capacity, FY2021 and FY2023', ['FY2021', 'FY2023'], 'Capacity, FY2021 and FY2023'),
    ('Capacity, FY2021 to FY2023', ['FY2021', '6M2023'], 'Capacity'),
    ('Capacity, FY2021 to FY2023', ['FY2021', None], 'Capacity'),
    ('Capacity, 2022-12-31 to 2023-12-31', ['2021-12-31', '2024-10-31'], 'Capacity'),
    ('Capacity, 2022-12-31 to 2023-12-31', ['2022-12-31', '2023-06-30', '2023-12-31'], 'Capacity, 2022-12-31 to 2023-12-31'),
    ('Capacity, 2022-12-31 to 2023-12-31 (continued)', ['FY2021', 'FY2023'], 'Capacity (continued)'),
    ('Capacity increased, FY2022 to FY2023', ['FY2021', 'FY2023'], 'Capacity increased, FY2022 to FY2023'),
])
def test_literal_period_inventory_is_checked_without_authoring_a_new_claim(title, periods, expected):
    records = [observation(str(i), 'Capacity', i + 1, period) for i, period in enumerate(periods)]
    before = deepcopy(records)
    assert source_scoped_heading(title, records) == expected
    assert records == before


def test_mixed_chart_periods_do_not_inherit_one_comparison_range_as_the_page_scope():
    title = 'Available capacity and throughput, 2022-12-31 to 2023-12-31'
    records = [observation(f'{metric}-{i}', metric, 10 + i, period, unit='count')
               for metric, periods in [('Capacity', ['2021-12-31', '2022-12-31', '2023-12-31', '2024-10-31']),
                                       ('Throughput', ['FY2021', 'FY2022', 'FY2023'])]
               for i, period in enumerate(periods)]
    charts = [ChartPlan(id=metric, title=metric, question='Reported observations', chart_type='bar',
                        observation_ids=[o.id for o in records if o.metric_original == metric], source_pages=[3])
              for metric in ('Capacity', 'Throughput')]
    plan = PresentationSlide(id='scope', slide_type='analysis', title=title, section_title=title,
        theme_id='scope', chart_ids=[c.id for c in charts], layout='two_up', source_pages=[3])
    result = result_for(records, charts, plan)
    topic = _topic('series', 'scope'); topic.title = title
    result.presentation_topics = PresentationTopicSelection(topics=[topic])
    before = result.model_dump()
    deck = blank_deck()
    rendered = render_composed_slide(deck, plan, charts, result, DocumentIndex(records))
    copy = [shape.text for shape in rendered[0].shapes if shape.has_text_frame]
    assert 'Available capacity and throughput' in copy and title not in copy
    assert title == json.loads(rendered[0].notes_slide.notes_text_frame.text)['planned_title']
    plotted = [shape.chart for slide in rendered for shape in slide.shapes if shape.has_chart]
    assert sum(len(chart.plots[0].categories) for chart in plotted) == 7
    assert result.model_dump() == before
    validate_composed_geometry(deck)


def test_six_source_entries_use_body_topics_and_fit_one_readable_page():
    topics = ['Production and product-category share of total output, FY2021 to FY2023',
              'Unit volume and average selling price', 'Output and conversion ratio',
              'Reported shortfall, adjusted shortfall and adjustments',
              'Available capacity, stock and throughput, 2022-12-31 to 2023-12-31',
              'Research expenditure and research/total operating expenditure']
    result = result_for([], [])
    result.presentation_plan.slides = []
    result.presentation_topics = PresentationTopicSelection(topics=[])
    for i, title in enumerate(topics):
        topic = _topic(f'series-{i}', str(i)); topic.title = title
        result.presentation_topics.topics.append(topic)
        periods = (['FY2021', '2021-12-31', 'FY2022', '2022-12-31', 'FY2023', '2023-12-31',
                    '2024-06-30', '2024-10-31'] if i == 4 else
                   ['6M2023', '6M2024'] if i == 2 else ['FY2021', 'FY2022', 'FY2023'])
        records = [observation(f'{i}-{n}', f'Measure {i}', n + 10, period) for n, period in enumerate(periods)]
        for n, item in enumerate(records):
            item.raw_unit = ('currency in thousands/unit' if i == 1 else
                             '%' if i in {0, 2, 5} and n == 0 else 'currency in thousands')
        result.observations.extend(records)
        chart = ChartPlan(id=f'chart-{i}', title=f'Measure {i}', question='Reported values',
                          chart_type='line', observation_ids=[o.id for o in records], source_pages=[3])
        result.charts.append(chart)
        plan = PresentationSlide(id=str(i), slide_type='analysis', theme_id=str(i), chart_ids=[chart.id],
                                 title='How do the cited measures compare?', section_title='How do the cited measures compare?')
        result.presentation_plan.slides.append(plan)
        result.presentation_export_trace.append(dict(planned_slide_id=str(i), chart_ids=[chart.id],
            observation_ids=[o.id for o in records], source_pages=[3], slide_numbers=[i + 1]))
    before = [o.model_dump() for o in result.observations]
    deck = blank_deck(); index = DocumentIndex(result.observations)
    entries = index_entries(result, index)
    pages = render_data_index(deck, result, index)
    assert len(pages) == 1
    assert entries[4]['topic'] == 'Available capacity, stock and throughput'
    assert all('?' not in entry['topic'] for entry in entries)
    shapes = [s for s in pages[0].shapes if s.name == 'data_index:entry']
    assert len(shapes) == 6 * 4
    assert all(p.font.size.pt == 12 for s in shapes for p in s.text_frame.paragraphs)
    visible = '\n'.join(s.text for s in shapes)
    assert all(period in visible for entry in entries for period in entry['periods'])
    assert all(unit in visible for entry in entries for unit in entry['units'])
    assert [o.model_dump() for o in result.observations] == before
    notes = json.loads(pages[0].notes_slide.notes_text_frame.text)
    assert notes['data_index'] == entries
    assert max(s.top.inches + s.height.inches for s in shapes) < deck.slide_height.inches - 1.10


def test_index_topic_period_scope_includes_every_planned_page_of_the_same_theme():
    title = 'Production, FY2021 to FY2023'
    records = [observation(str(i), 'Production', 10 + i, period)
               for i, period in enumerate(['FY2020', 'FY2021', 'FY2023'])]
    charts = [ChartPlan(id='earlier', title='Earlier production', question='Reported production',
                       chart_type='bar', observation_ids=['0'], source_pages=[3]),
              ChartPlan(id='later', title='Later production', question='Reported production',
                       chart_type='bar', observation_ids=['1', '2'], source_pages=[3])]
    result = result_for(records, charts)
    topic = _topic('series', 'production'); topic.title = title
    result.presentation_topics = PresentationTopicSelection(topics=[topic])
    result.presentation_plan.slides = [PresentationSlide(id=chart.id, slide_type='analysis',
        theme_id='production', chart_ids=[chart.id], title=title, section_title=title) for chart in charts]
    result.presentation_export_trace = [dict(planned_slide_id=chart.id, chart_ids=[chart.id],
        observation_ids=chart.observation_ids, source_pages=[3], slide_numbers=[i + 1])
        for i, chart in enumerate(charts)]
    before = result.model_dump()
    entries = index_entries(result, DocumentIndex(records))
    assert len(entries) == 1
    assert entries[0]['topic'] == 'Production'
    assert entries[0]['slides'] == [1, 2]
    assert entries[0]['periods'] == ['FY2020', 'FY2021', 'FY2023']
    assert entries[0]['observation_ids'] == ['0', '1', '2']
    assert result.model_dump() == before
