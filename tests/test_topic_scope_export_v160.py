"""Mixed-metric questions survive share-copy recovery without weakening evidence."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.models import ChartPlan
from adaptive_document_agent.services.presentation_claim_evidence import _narrow, prepare_presentation_claims
from adaptive_document_agent.services.presentation_share_claims import share_claims
from adaptive_document_agent.validation.presentation_topic_relations import TopicRelationValidator
from tests.test_evidence_bound_topic_panels import relation_result
from tests.test_presentation_claim_evidence import _sample


@pytest.mark.parametrize("phrase", ["as a share of", "as the share of", "as a proportion of"])
def test_ratio_phrase_is_not_split_by_an_earlier_share_clause(phrase):
    result = _sample()
    text = f"Enterprise share rose; Consumer {phrase} revenue fell."
    claims = share_claims(result.observations, text)
    assert claims is not None and len(claims) == 2
    assert [(c.subject, c.denominator) for c in claims] == [("Enterprise", ""), ("Consumer", "revenue")]
    assert claims[1].text == f"Consumer {phrase} revenue fell"


def test_as_still_separates_two_independent_share_assertions():
    claims = share_claims(_sample().observations,
                          "Enterprise share rose as Consumer share fell.")
    assert claims is not None
    assert [c.subject for c in claims] == ["Enterprise", "Consumer"]


@pytest.mark.parametrize("wrong", [False, True])
def test_ratio_phrase_still_requires_the_exact_reported_denominator(wrong):
    result = _sample()
    for item in result.observations[:4]:
        item.evidence[0].column_label = "% of revenue"
    slide = result.presentation_plan.slides[-1]
    slide.observation_ids = [o.id for o in result.observations[:4]]
    slide.title = "Enterprise share rose; Consumer as a share of revenue fell."
    if wrong:
        slide.title = slide.title.replace("of revenue", "of units")
    original = slide.title
    before = deepcopy(result.observations)
    prepare_presentation_claims(result)
    assert slide.title == ("Customer mix" if wrong else original)
    assert result.observations == before


def test_narrowing_preserves_the_complete_authored_neutral_question():
    result = _sample()
    slide = result.presentation_plan.slides[-1]
    slide.section_title = "Revenue, product mix and gross profit as a share of revenue"
    slide.analytical_question = "How did revenue, product mix and gross profit as a share of revenue change?"
    before = (list(slide.chart_ids), list(slide.observation_ids))
    _narrow(slide, {}, result.observations)
    assert slide.title == slide.section_title == slide.message == slide.analytical_question
    assert (slide.chart_ids, slide.observation_ids) == before
    snapshot = slide.model_dump()
    _narrow(slide, {}, result.observations)
    assert slide.model_dump() == snapshot


def mixed_scope():
    result, slide = relation_result(["Revenue", "Gross profit margin"], [100, 40],
        title="Revenue and gross profit margin", rationale="Compare the two reported measures.")
    result.observations[0].unit = "currency"
    result.observations[0].unit_family = "currency"
    _, lookup = series_directory(result)
    result.presentation_topics.topics[0].series_ids = list(lookup)
    slide.title = slide.section_title = "Revenue"
    slide.comparison_mode = "parallel"
    return result, slide


def test_model_selected_parallel_scope_accepts_both_units_after_caption_narrowing():
    result, slide = mixed_scope()
    margin = result.observations[1]
    relation = TopicRelationValidator(result).relation(margin, slide)
    assert relation.kind == "selected_topic_scope"
    assert relation.observation_ids == (margin.id,)
    assert not TopicRelationValidator(result).mismatch(margin, slide)


@pytest.mark.parametrize("change", ["unselected", "foreign_theme", "unlinked", "undeclared",
                                    "invalid", "anomaly", "missing_source", "like_for_like"])
def test_parallel_scope_cannot_license_unowned_or_undeclared_evidence(change):
    result, slide = mixed_scope()
    margin = result.observations[1]
    topic, theme = result.presentation_topics.topics[0], result.presentation_plan.themes[0]
    if change == "unselected":
        _, lookup = series_directory(result)
        topic.series_ids = [sid for sid, rows in lookup.items() if margin.id not in {o.id for o in rows}]
    elif change == "foreign_theme": theme.observation_ids.remove(margin.id)
    elif change == "unlinked": slide.observation_ids.remove(margin.id)
    elif change == "undeclared": topic.title = topic.question = "Revenue"
    elif change == "invalid": margin.validation_status = "invalid"
    elif change == "anomaly": margin.anomaly_notes = ["Conflicting source"]
    elif change == "missing_source": margin.evidence = []
    else: slide.comparison_mode = "like_for_like"
    assert TopicRelationValidator(result).mismatch(margin, slide)


def test_chart_linked_scope_is_owned_but_does_not_relax_its_own_caption():
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa
    result, slide = mixed_scope()
    margin = result.observations[1]
    result.charts = [ChartPlan(id="margin", title="Revenue", question="How did revenue change?",
                              chart_type="bar", observation_ids=[margin.id], source_pages=[234])]
    slide.observation_ids = []
    slide.chart_ids = ["margin"]
    theme = result.presentation_plan.themes[0]
    theme.observation_ids = []
    theme.chart_ids = ["margin"]
    result.presentation_plan.slides[3] = slide
    assert not TopicRelationValidator(result).mismatch(margin, slide)
    qa = run_comprehensive_qa(result, auto_repair=False)
    assert any(i.code == "chart_title_data_mismatch" for i in qa.critical_errors)
