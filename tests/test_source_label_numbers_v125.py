import pytest
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models import PresentationTopicSelection
from adaptive_document_agent.validation.source_label_numbers import without_source_label_annotations
from tests.test_topic_coverage_review import _observation, _topic


def test_percent_header_support_is_identical_in_topic_and_slide_validation():
    observations=[_observation('Rate','FY2023',13.7),_observation('Rate','FY2024',20.2)]
    for o in observations:
        o.unit,o.raw_unit,o.unit_family='percent','%','percentage'
    topic=_topic('rate')
    topic.takeaway='Rate was 13.7% in FY2023 and 20.2% in FY2024.'
    selection=PresentationTopicSelection(topics=[topic])
    PresentationTopicSelector._validate(selection,{'rate':observations})
    for o in observations:
        o.unit,o.raw_unit,o.unit_family='count','units','count'
    with pytest.raises(ValueError,match='unsupported numeric'):
        PresentationTopicSelector._validate(selection,{'rate':observations})


@pytest.mark.parametrize('prefix', ['', '• '])
def test_literal_metric_annotation_does_not_authorize_an_unrelated_amount(prefix):
    observations=[_observation(prefix+'Widget revenue(6)','FY2023',100),_observation(prefix+'Widget revenue(6)','FY2024',200)]
    topic=_topic('widgets')
    topic.title='Widget revenue(6)'
    topic.takeaway='Widget revenue(6) was 100 in FY2023 and 200 in FY2024.'
    selection=PresentationTopicSelection(topics=[topic])
    PresentationTopicSelector._validate(selection,{'widgets':observations})
    assert without_source_label_annotations('Widget revenue(6) was 6.',observations)=='Widget revenue was 6.'
    assert without_source_label_annotations('Other revenue(6)',observations)=='Other revenue(6)'
    topic.takeaway='Widget revenue(6) was 6 in FY2024.'
    with pytest.raises(ValueError,match='unsupported numeric'):
        PresentationTopicSelector._validate(selection,{'widgets':observations})
