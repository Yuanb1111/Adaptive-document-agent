import pytest

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models import PresentationTopicSelection
from adaptive_document_agent.validation.topic_source_notation import without_topic_source_notation
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator as V
from tests.test_topic_coverage_review import _fixture, _topic


@pytest.mark.parametrize('prose', [
    'Annual and 6M periods are separate.',
    'The annual and 6M composition views retain all categories.',
    'Annual and 6M category-mix periods are separate.',
    'The 6M comparison tests the latest interim continuation.',
    'The annual and 6M cash-flow views test the latest interim.',
    'The 6M share tests the latest interim.',
    'The source definition is presented on page 234.',
])
def test_source_notation_needs_no_model_correction(prose):
    _, _, lookup, annual, interim, _ = _fixture()
    for item in lookup[interim]:
        item.unit = 'percent'
    topic = _topic(interim)
    topic.rationale = prose
    before = [o.model_dump() for o in lookup[interim]]
    PresentationTopicSelector._validate(PresentationTopicSelection(topics=[topic]), lookup)
    assert topic.rationale == prose
    assert [o.model_dump() for o in lookup[interim]] == before


@pytest.mark.parametrize('prose', [
    'Revenue reached 6M.', 'Annual revenue reached 6M.',
    'USD 6M comparison', '$6M comparison', '6M USD comparison',
    'Annual and USD 6M periods', 'Annual and 6M USD periods',
    'Annual and 6M shares', 'Annual and 6M revenue',
    '-6M comparison', '+6M comparison', '人民币 6M comparison',
    '- 6M comparison', '+ 6M comparison',
    'The 9M comparison', 'The 6M shares were issued.',
    'Source page 234 reports revenue of 234.',
])
def test_notation_never_authorizes_money_or_other_numbers(prose):
    _, _, lookup, _, interim, _ = _fixture()
    text = without_topic_source_notation(prose, lookup[interim])
    assert V._numbers(text)
    topic = _topic(interim)
    topic.rationale = prose
    with pytest.raises(ValueError, match='unsupported numeric'):
        PresentationTopicSelector._validate(PresentationTopicSelection(topics=[topic]), lookup)


def test_page_ownership_is_required_even_when_number_matches_a_value():
    _, _, lookup, _, interim, _ = _fixture()
    with pytest.raises(ValueError, match='outside its selected source'):
        without_topic_source_notation('See page 90.', lookup[interim])
    assert V._numbers(without_topic_source_notation('See page 234. Value 90.', lookup[interim])) == {'90'}


def test_source_duration_and_percentage_context_are_required():
    _, _, lookup, annual, interim, _ = _fixture()
    assert V._numbers(without_topic_source_notation('The 6M comparison', lookup[annual])) == {'6'}
    assert V._numbers(without_topic_source_notation('The 6M share', lookup[interim])) == {'6'}
