"""Selected caveats declare support scope only with independent source proof."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.validation.presentation_topic_relations import TopicRelationValidator
from tests.test_evidence_bound_topic_panels import relation_result


def adjustment_scope():
    result, slide = relation_result(
        ['Reported loss', 'Share-based payments expense', 'Listing expenses', 'Adjusted net loss'],
        [-80, 12, 8, -60], title='Reported loss and adjusted net loss',
        rationale='Compare the reported and adjusted outcomes and their disclosed adjustments.',
        source='We define adjusted net loss as reported loss adjusted for share-based payments expense and listing expenses.',
        unit='currency')
    topic = result.presentation_topics.topics[0]
    topic.caveats = ['Listing expenses have no prior-period comparative in the extracted evidence.']
    slide.comparison_mode = 'parallel'
    result.presentation_plan.slides = [slide]
    return result, slide, result.observations[2]


def test_caveat_declared_selected_adjustment_requires_and_retains_source_definition():
    result, slide, item = adjustment_scope()
    before = deepcopy(result)
    relation = TopicRelationValidator(result).relation(item, slide)
    assert relation is not None and relation.kind == 'source_definition'
    assert relation.observation_ids[0] == item.id
    assert relation.source_quote == result.document.pages[0].text
    assert relation.source_pages == (234,)
    assert not TopicRelationValidator(result).mismatch(item, slide)
    assert result == before


@pytest.mark.parametrize('fault', ['no_definition', 'cooccurrence', 'negation', 'no_declaration',
    'unselected', 'foreign_theme', 'foreign_slide', 'different_table', 'different_period',
    'different_entity', 'different_currency', 'invalid', 'anomaly', 'unsourced'])
def test_caveat_does_not_license_unproven_or_unowned_support(fault):
    result, slide, item = adjustment_scope()
    if fault == 'no_definition': result.document.pages[0].text = ''
    elif fault == 'cooccurrence': result.document.pages[0].text = 'Reported loss, adjusted net loss and listing expenses are shown.'
    elif fault == 'negation': result.document.pages[0].text = 'Adjusted net loss does not include listing expenses.'
    elif fault == 'no_declaration': result.presentation_topics.topics[0].caveats.clear()
    elif fault == 'unselected':
        _, lookup = series_directory(result)
        result.presentation_topics.topics[0].series_ids = [sid for sid, rows in lookup.items()
                                                         if item.id not in {o.id for o in rows}]
    elif fault == 'foreign_theme': result.presentation_plan.themes[0].observation_ids.remove(item.id)
    elif fault == 'foreign_slide': slide.observation_ids.remove(item.id)
    elif fault == 'different_table': item.table_id = item.evidence[0].table_id = 'another-table'
    elif fault == 'different_period': item.period = 'FY2023'
    elif fault == 'different_entity': item.entity = 'Another entity'
    elif fault == 'different_currency': item.currency = 'USD'
    elif fault == 'invalid': item.validation_status = 'invalid'
    elif fault == 'anomaly': item.anomaly_notes = ['Conflicting evidence']
    else: item.evidence.clear()
    assert TopicRelationValidator(result).mismatch(item, slide)


def test_caveat_cannot_establish_direct_parallel_topic_scope():
    result, slide, item = adjustment_scope()
    result.document.pages[0].text = 'Listing expenses and adjusted net loss are listed in this table.'
    assert TopicRelationValidator(result).relation(item, slide) is None


def test_source_support_cannot_override_own_chart_caption():
    from adaptive_document_agent.models import ChartPlan
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa
    result, slide, item = adjustment_scope()
    result.charts = [ChartPlan(id='wrong-caption', title='Adjusted net loss',
        question='What is adjusted net loss?', chart_type='bar', observation_ids=[item.id], source_pages=[234])]
    slide.chart_ids = ['wrong-caption']
    qa = run_comprehensive_qa(result, auto_repair=False)
    assert not any(e.code == 'slide_topic_mismatch' and item.id in e.related_ids for e in qa.critical_errors)
    assert any(e.code == 'chart_title_data_mismatch' for e in qa.critical_errors)
