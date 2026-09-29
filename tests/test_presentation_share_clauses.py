"""Each share predicate retains its own metric, denominator and direction."""

import copy

import pytest

from adaptive_document_agent.models import PresentationTopic, PresentationTopicSelection
from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.services.presentation_claim_evidence import prepare_presentation_claims
from tests.test_presentation_claim_evidence import _sample


def _two_subjects():
    result = _sample()
    slide = result.presentation_plan.slides[-1]
    slide.observation_ids = [o.id for o in result.observations[:4]]
    slide.title = "Enterprise's share expanded and Consumer's share contracted."
    return result, slide


def test_independent_share_directions_keep_both_source_rows_and_raw():
    result, slide = _two_subjects()
    title, raw = slide.title, copy.deepcopy(result.observations)
    prepare_presentation_claims(result)
    assert slide.title == title
    assert set(slide.visual_blocks[0].observation_ids) == {o.id for o in raw[:4]}
    assert raw == result.observations
    snapshot = result.model_dump()
    prepare_presentation_claims(result)
    assert snapshot == result.model_dump()


@pytest.mark.parametrize("title", [
    "Enterprise's share contracted and Consumer's share contracted.",
    "Enterprise's share expanded and Consumer's share expanded.",
    "Enterprise and Consumer increased their share.",
    "Enterprise's and Consumer's shares contracted.",
])
def test_no_subject_can_borrow_another_subjects_direction(title):
    result, slide = _two_subjects()
    slide.title = title
    prepare_presentation_claims(result)
    assert slide.title == "Customer mix"


@pytest.mark.parametrize("wrong_denominator", [False, True])
def test_independent_clauses_bind_explicit_denominators(wrong_denominator):
    result, slide = _two_subjects()
    for item in result.observations[:2]:
        item.evidence[0].column_label = "% of revenue"
    for item in result.observations[2:4]:
        item.evidence[0].column_label = "% of units"
    slide.title = "Enterprise's share of revenue expanded and Consumer's share of units contracted."
    if wrong_denominator:
        slide.title = slide.title.replace("Consumer's share of units", "Consumer's share of revenue")
    original = slide.title
    prepare_presentation_claims(result)
    assert slide.title == ("Customer mix" if wrong_denominator else original)


@pytest.mark.parametrize("qualification", ["", "Consumer", "Enterprise"])
def test_negative_source_percentages_use_only_same_row_magnitude_qualification(qualification):
    result = _sample()
    slide = result.presentation_plan.slides[-1]
    for item, value in zip(result.observations[:2], (-49.5, -56.5)):
        item.value, item.raw_value = value, f"({abs(value)})"
        item.evidence[0].column_label = "%of Revenue"
    slide.title = "Enterprise took a larger share of revenue."
    if qualification:
        result.presentation_plan.themes[0].caveats = [
            f"{qualification} is reported as a negative percentage of revenue; direction refers to its magnitude."]
    original, raw = slide.title, copy.deepcopy(result.observations)
    prepare_presentation_claims(result)
    assert slide.title == (original if qualification == "Enterprise" else "Customer mix")
    assert result.observations == raw


@pytest.mark.parametrize("population,table,expected", [
    ("revenue", "sales", True), ("units", "sales", False), ("revenue", "other", False),
])
def test_explicit_total_population_comes_only_from_exact_source_table_caption(population, table, expected):
    result = _sample()
    result.document.pages[1].tables = [ExtractedTable(table_id=table, page=2,
        raw_header_lines=[f"The following table sets forth a breakdown of our {population} by category for the years indicated."])]
    slide = result.presentation_plan.slides[-1]
    slide.title = "Enterprise increased its share of total revenue."
    original = slide.title
    prepare_presentation_claims(result)
    assert slide.title == (original if expected else "Customer mix")


@pytest.mark.parametrize("valid", [False, True])
def test_cached_narrowing_revalidates_retained_topic_without_overwriting_new_repairs(valid):
    result = _sample()
    plan, slide = result.presentation_plan, result.presentation_plan.slides[-1]
    claim = "Enterprise share expanded." if valid else "Enterprise share contracted."
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id="mix", title="Customer mix", question="How did the mix evolve?",
        rationale="The model selected the mix change.", takeaway=claim)])
    slide.title = "Customer mix"
    slide.selection_reason = "The retained records support these reported values; the broader comparison was omitted."
    plan.slides[0].bullets = [slide.title]
    raw = result.presentation_topics.model_dump()
    prepare_presentation_claims(result)
    assert slide.title == (claim if valid else "Customer mix")
    assert plan.slides[0].bullets == [slide.title]
    assert result.presentation_topics.model_dump() == raw
    snapshot = result.model_dump()
    prepare_presentation_claims(result)
    assert snapshot == result.model_dump()
    if valid:
        slide.title = "Enterprise share expanded over FY2022 and FY2023."
        repaired = slide.title
        prepare_presentation_claims(result)
        assert slide.title == repaired


def test_conjunction_inside_source_row_is_not_a_clause_boundary():
    result = _sample()
    for item in result.observations:
        if item.evidence[0].row_label == "Enterprise":
            item.evidence[0].row_label = "Research and development"
            if item.unit == "percent":
                item.evidence[0].column_label = "% of revenue"
    slide = result.presentation_plan.slides[-1]
    slide.title = "Research and development took a larger share of revenue."
    original = slide.title
    prepare_presentation_claims(result)
    assert slide.title == original


@pytest.mark.parametrize("correct", [False, True])
def test_revenue_share_modifier_cannot_borrow_a_percentage_of_units(correct):
    result = _sample()
    for item in result.observations[:2]:
        item.evidence[0].column_label = "% of revenue" if correct else "% of units"
    slide = result.presentation_plan.slides[-1]
    slide.title = "Enterprise's revenue share expanded."
    original = slide.title
    prepare_presentation_claims(result)
    assert slide.title == (original if correct else "Customer mix")


@pytest.mark.parametrize("valid", [False, True])
def test_long_summary_takeaway_gets_independent_share_validation_and_visible_support(valid):
    result, slide = _two_subjects()
    slide.title = "Customer mix"
    summary = result.presentation_plan.slides[0]
    summary.bullet_observation_ids = [[o.id for o in result.observations]]
    text = ("Enterprise's share expanded substantially across the supplied reporting periods while "
            "Consumer's share contracted over the same comparable annual periods.")
    if not valid:
        text = text.replace("Consumer's share contracted", "Consumer's share expanded")
    summary.bullets = [text]
    assert len(text.split()) > 18
    prepare_presentation_claims(result)
    assert summary.bullets == [text if valid else "Customer mix"]
    if valid:
        assert set(slide.visual_blocks[0].observation_ids) == {o.id for o in result.observations[:4]}
    else:
        assert not slide.visual_blocks
    snapshot = result.model_dump()
    prepare_presentation_claims(result)
    assert snapshot == result.model_dump()


def test_provenance_only_other_period_does_not_expand_displayed_share_claim():
    from tests.test_presentation_claim_evidence import _observation
    result = _sample()
    slide = result.presentation_plan.slides[-1]
    additional = [_observation("Enterprise", 2024, 10), _observation("Enterprise", 2024, 900, share=False)]
    result.observations.extend(additional)
    slide.observation_ids.extend(item.id for item in additional)
    original = slide.title
    prepare_presentation_claims(result)
    assert slide.title == original
    assert set(slide.visual_blocks[0].observation_ids) == {item.id for item in result.observations[:2]}
    snapshot = result.model_dump()
    prepare_presentation_claims(result)
    assert result.model_dump() == snapshot


def test_summary_uses_visible_source_before_original_duplicate_source_refs():
    from tests.test_presentation_claim_evidence import _observation
    result = _sample()
    slide, summary = result.presentation_plan.slides[-1], result.presentation_plan.slides[0]
    slide.title = "Customer mix"
    result.observations.extend([_observation("Enterprise", 2022, 90, table="aaa_original"),
                                _observation("Enterprise", 2023, 20, table="aaa_original")])
    text = ("Enterprise's share expanded over the comparable annual periods presented in the "
            "source table, with the same category definition retained.")
    summary.bullets = [text]
    summary.bullet_observation_ids = [[item.id for item in result.observations]]
    prepare_presentation_claims(result)
    assert summary.bullets == [text]
    assert set(slide.visual_blocks[0].observation_ids) == {item.id for item in result.observations[:2]}
    snapshot = result.model_dump()
    prepare_presentation_claims(result)
    assert result.model_dump() == snapshot


@pytest.mark.parametrize("claim,valid", [
    ("North America sales volume and revenue share expanded.", True),
    ("North America sales volume and revenue share contracted.", False),
    ("North America sales volume and units share expanded.", False),
])
def test_source_row_prefix_and_compound_measure_share_claim(claim, valid):
    result = _sample()
    slide = result.presentation_plan.slides[-1]
    selected = [item for item in result.observations if item.evidence[0].row_label == "Enterprise"]
    for item in selected:
        item.evidence[0].row_label = "North America customers"
        if item.unit == "percent":
            item.evidence[0].column_label = "% of revenue"
    slide.observation_ids = [item.id for item in selected]
    slide.title = claim
    raw = copy.deepcopy(result.observations)
    prepare_presentation_claims(result)
    assert slide.title == (claim if valid else "Customer mix")
    assert result.observations == raw
    if valid:
        assert {item.id for item in selected if item.unit == "percent"} <= {
            oid for block in slide.visual_blocks for oid in block.observation_ids
        }


def test_short_row_prefix_must_identify_one_source_row():
    result = _sample()
    slide = result.presentation_plan.slides[-1]
    for item in result.observations:
        item.evidence[0].row_label = ("North America customers" if item.evidence[0].row_label == "Enterprise"
                                      else "North America outlets")
        if item.unit == "percent":
            item.evidence[0].column_label = "% of revenue"
    slide.observation_ids = [item.id for item in result.observations]
    slide.title = "North America sales volume and revenue share expanded."
    prepare_presentation_claims(result)
    assert slide.title == "Customer mix"
