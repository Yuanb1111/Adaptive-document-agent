"""Exact semantic review survives wording changes that confuse legacy keywords."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.agent.topic_evidence_review import topic_binding
from adaptive_document_agent.models import ChartPlan, ValidationIssue
from adaptive_document_agent.validation.presentation_topic_relations import TopicRelationValidator
from tests.test_evidence_bound_topic_panels import relation_result


def reviewed_scope():
    result, slide = relation_result(['Inventory turnover days'], [190],
        title='Operating cash and working-capital intensity',
        rationale='Inventory turnover days describe the selected working-capital measure.', unit='days')
    slide.comparison_mode = 'parallel'
    _, lookup = series_directory(result)
    topic = result.presentation_topics.topics[0]
    topic.question = slide.message = 'How did operating cash flow and working-capital intensity evolve?'
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_evidence_review', stage='report',
        message=json.dumps(dict(accepted_bindings=[topic_binding(topic, lookup)]))))
    return result, slide


def test_exact_review_allows_owned_parallel_panel_without_editing_copy_or_facts():
    result, slide = reviewed_scope()
    before = deepcopy(result)
    validator = TopicRelationValidator(result)
    observation = result.observations[0]
    assert validator.relation(observation, slide).kind == 'selected_topic_scope'
    assert not validator.mismatch(observation, slide)
    assert result == before


@pytest.mark.parametrize('change', ['absent', 'copy', 'value', 'evidence', 'unselected',
                                    'foreign_theme', 'unlinked', 'invalid', 'like_for_like'])
def test_semantic_approval_cannot_cover_stale_unowned_or_unreviewed_rows(change):
    result, slide = reviewed_scope()
    observation = result.observations[0]
    topic = result.presentation_topics.topics[0]
    if change == 'absent': result.validation_warnings.clear()
    elif change == 'copy': topic.rationale += ' Different relationship.'
    elif change == 'value': observation.value += 1
    elif change == 'evidence': observation.evidence[0].text = 'Changed source'
    elif change == 'unselected': topic.series_ids = []
    elif change == 'foreign_theme': slide.theme_id = 'other'
    elif change == 'unlinked': slide.observation_ids = []
    elif change == 'invalid': observation.validation_status = 'invalid'
    else: slide.comparison_mode = 'like_for_like'
    assert TopicRelationValidator(result).mismatch(observation, slide)


def test_semantic_panel_scope_still_rejects_an_incorrect_chart_caption():
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa
    result, slide = reviewed_scope()
    item = result.observations[0]
    result.charts = [ChartPlan(id='wrong', title='Operating cash flow',
        question='How did operating cash flow change?', chart_type='bar',
        observation_ids=[item.id], source_pages=[234])]
    slide.chart_ids, slide.observation_ids = ['wrong'], []
    theme = result.presentation_plan.themes[0]
    theme.chart_ids, theme.observation_ids = ['wrong'], []
    result.presentation_plan.slides[3] = slide
    assert not TopicRelationValidator(result).mismatch(item, slide)
    qa = run_comprehensive_qa(result, auto_repair=False)
    assert any(i.code == 'chart_title_data_mismatch' for i in qa.critical_errors)
