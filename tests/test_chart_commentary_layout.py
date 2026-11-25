from io import BytesIO

from pptx import Presentation

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import ChartPlan, PresentationSlide
from adaptive_document_agent.models.customization import ReportRequirement, ReportRequirements
from adaptive_document_agent.services.slide_compositor import render_composed_slide, validate_composed_geometry
from tests.test_chart_capacity_pagination import _deck
from tests.test_p0_composition import observation, result_for


def test_bounded_chart_keeps_every_qualification_visible_with_one_native_plot():
    observations = [observation(f'volume-{i}', 'Volume', value, f'FY{2020+i}', unit='count')
                    for i, value in enumerate([28, 37, 32, 45])]
    chart = ChartPlan(id='volume', title='Volume', chart_type='line', question='Reported volume',
                      observation_ids=[r.id for r in observations], source_pages=[3])
    sentences = [f'For region {label} the publication describes the boundary of the measured service '
                 'and gives the original reporting period for the comparison.' for label in 'ABCDEF']
    plan = PresentationSlide(id='find', slide_type='analysis', title='Volume', chart_ids=[chart.id],
                             bullets=[' '.join(sentences[i:i+2]) for i in range(0, len(sentences), 2)],
                             source_pages=[3])
    result = result_for(observations, [chart], plan)
    index = DocumentIndex(observations)
    ordinary = render_composed_slide(_deck(), plan, [chart], result, index)
    result.profile.report_requirements = ReportRequirements(items=[
        ReportRequirement(id='body', kind='slide_limit', max_slides=6, request_quote='Six body slides',
                          description='Physical body limit', slide_scope='body')])
    deck = _deck()
    compact = render_composed_slide(deck, plan, [chart], result, index)
    assert len(compact) == 1 < len(ordinary)
    validate_composed_geometry(deck)
    stream = BytesIO()
    deck.save(stream)
    slide, = Presentation(BytesIO(stream.getvalue())).slides
    visible = ' '.join(' '.join(s.text.split()) for s in slide.shapes if s.has_text_frame)
    assert all(visible.count(sentence) == 1 for sentence in sentences)
    assert 'Source:' in visible
    native, = [s.chart for s in slide.shapes if s.has_chart]
    assert list(native.series[0].values) == [28, 37, 32, 45]
