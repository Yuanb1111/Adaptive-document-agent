"""Percentage tokens require typed, theme-owned source evidence."""

import copy

import pytest

from adaptive_document_agent.models import PresentationTopic, PresentationTopicSelection
from adaptive_document_agent.services.presentation_claim_evidence import prepare_presentation_claims
from adaptive_document_agent.validation.narrative_plan_validator import validate_narrative_plan
from tests.test_presentation_claim_evidence import _sample


def percentage_plan():
    result = _sample()
    plan = result.presentation_plan
    theme, slide = plan.themes[0], plan.slides[-1]
    theme.title = "Enterprise share was 30% in FY2022 and 60% in FY2023"
    theme.chart_ids = []
    theme.observation_ids = [o.id for o in result.observations[:2]]
    slide.chart_ids = []
    slide.observation_ids = list(theme.observation_ids)
    return result


@pytest.mark.parametrize("typed_by", ["unit", "unit_family"])
def test_bare_numeric_cells_license_percent_only_with_explicit_source_type(typed_by):
    result = percentage_plan()
    if typed_by == "unit_family":
        for item in result.observations[:2]:
            item.unit = "generic"
            item.unit_family = "percentage"
    before = copy.deepcopy(result.observations)
    assert not validate_narrative_plan(result.presentation_plan, result)
    assert result.observations == before


@pytest.mark.parametrize("mutation,token", [
    ("invented", "999%"), ("unowned", "70%"),
    ("count", "30%"), ("currency", "30%"),
    ("ratio", "30%"), ("percentage_points", "30%"),
])
def test_unreported_or_untyped_percentages_remain_rejected(mutation, token):
    result = percentage_plan()
    if mutation in {"invented", "unowned"}:
        result.presentation_plan.themes[0].title = "Enterprise share was " + token
    else:
        for item in result.observations[:2]:
            item.unit = mutation
            item.unit_family = mutation
    errors = validate_narrative_plan(result.presentation_plan, result)
    assert any("unsupported numeric claims" in error and token in error for error in errors)


@pytest.mark.parametrize("cached", [False, True])
def test_share_restoration_keeps_topic_headers_and_complete_claim_distinct(cached):
    result = _sample()
    plan, slide = result.presentation_plan, result.presentation_plan.slides[-1]
    label, claim = "Customer mix", "Enterprise share expanded."
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id="mix", title=label, question="How did the mix evolve?",
        rationale="Selected sales mix question.", takeaway=claim)])
    slide.title = claim if cached else label
    slide.section_title = claim if cached else label
    plan.themes[0].title = slide.section_title
    if not cached:
        slide.selection_reason = "The retained records support these reported values; the broader comparison was omitted."
    plan.slides[0].bullets = [slide.title]
    raw = copy.deepcopy(result.observations)
    topics = result.presentation_topics.model_dump()
    prepare_presentation_claims(result)
    assert slide.title == claim
    assert plan.slides[0].bullets == [claim]
    assert slide.section_title == plan.themes[0].title == label
    assert result.observations == raw
    assert result.presentation_topics.model_dump() == topics
    snapshot = result.model_dump()
    prepare_presentation_claims(result)
    assert result.model_dump() == snapshot


def test_cache_header_migration_preserves_other_model_repairs():
    result = _sample()
    slide = result.presentation_plan.slides[-1]
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id="mix", title="Customer mix", question="How did the mix evolve?",
        rationale="Selected sales mix question.", takeaway=slide.title)])
    slide.section_title = result.presentation_plan.themes[0].title = "Reported sales composition"
    prepare_presentation_claims(result)
    assert slide.section_title == result.presentation_plan.themes[0].title == "Reported sales composition"
