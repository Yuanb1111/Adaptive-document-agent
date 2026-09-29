"""Topic selection survives duplicated sources, old cached caps and pagination."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.agent.presentation_summary_selection import (
    rebuild_selected_topic_summary, sync_selected_topic_summary_evidence,
)
from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import (
    AnalysisResult, ChartPlan, DocumentProfile, Insight, Observation, ParsedDocument, PipelineResult,
    PresentationPlan, PresentationSlide, PresentationTheme, PresentationTopic,
    PresentationTopicSelection, SourceEvidence,
)
from adaptive_document_agent.services.pptx_export import _add_planned_summary
from adaptive_document_agent.services.presentation_claim_evidence import prepare_presentation_claims
from tests.test_presentation_brief import blank_deck, visible
from tests.test_summary_coverage import _assert_readable_geometry, _bodies


def _topic_result(count=6, copies=3):
    result = PipelineResult(
        document=ParsedDocument(document_id="study", sha256="local", safe_filename="study.pdf", page_count=100),
        profile=DocumentProfile(document_type="Study", analysis_page_ranges=[(1, 100)]),
    )
    themes = []
    for i in range(count):
        label = f"Subject {chr(65 + i)}"
        ids = []
        for copy in range(copies):
            for year, value in ((2023, 10), (2024, 11), (2025, 12)):
                oid = f"subject-{i}-{copy}-{year}"
                ids.append(oid)
                result.observations.append(Observation(
                    id=oid, metric_original=label, metric_canonical=label.lower(),
                    value=value, raw_value=str(value), unit="count", raw_unit="count", period=f"FY{year}",
                    period_type="fiscal_year", period_basis="FY", confidence=.99,
                    evidence=[SourceEvidence(page=i * 10 + copy + 1, text=f"{label} {year}: {value}",
                                             extraction_method="digital_table", confidence=.99)],
                ))
        result.charts.append(ChartPlan(id=f"chart-{i}", title=label, chart_type="line",
                                      question=f"How did {label} compare?", observation_ids=ids[:3],
                                      source_pages=[i * 10 + 1]))
        themes.append(PresentationTheme(id=f"topic-{i}", title=label, question=f"How did {label} compare?",
                                        rationale="Comparable annual source records are available.",
                                        observation_ids=ids, chart_ids=[f"chart-{i}"],
                                        source_pages=list(range(i * 10 + 1, i * 10 + copies + 1))))
    directory, _ = series_directory(result)
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id=theme.id, title=theme.title, question=theme.question, rationale=theme.rationale,
        takeaway=f"{theme.title} is reported across the annual observations.",
        series_ids=[next(item["id"] for item in directory if item["metric"] == theme.title)],
    ) for theme in themes])
    result.presentation_plan = PresentationPlan(title="Study findings", planning_origin="topic_compilation",
        themes=themes, slides=[PresentationSlide(id="summary", slide_type="executive_summary", title="Summary")])
    return result


def test_all_eight_model_topics_survive_duplicate_evidence_and_roundtrip():
    result = _topic_result(count=8)
    raw = deepcopy(result.observations)
    selected = deepcopy(result.presentation_topics)
    assert rebuild_selected_topic_summary(result, result.presentation_plan)
    summary = result.presentation_plan.slides[0]

    assert summary.bullets == [topic.takeaway for topic in selected.topics]
    assert len(summary.observation_ids) == 72
    assert summary.bullet_observation_ids == [theme.observation_ids for theme in result.presentation_plan.themes]
    assert summary.source_pages == sorted({e.page for item in raw for e in item.evidence})
    assert PresentationPlan.model_validate_json(result.presentation_plan.model_dump_json()) == result.presentation_plan
    assert result.observations == raw
    assert result.presentation_topics == selected


def test_duplicate_source_count_does_not_change_selected_topic_order():
    single, repeated = _topic_result(copies=1), _topic_result(copies=3)
    for result in (single, repeated):
        rebuild_selected_topic_summary(result, result.presentation_plan)
    assert single.presentation_plan.slides[0].bullets == repeated.presentation_plan.slides[0].bullets
    assert len(repeated.presentation_plan.slides[0].observation_ids) == 54


def test_export_preparation_reconciles_summary_duplicates_after_topic_rebuild():
    result = _topic_result(count=1, copies=2)
    for item in result.observations:
        item.dimensions["table_context"] = f"source-{item.evidence[0].page}"
    original = deepcopy(result.observations)
    prepare_presentation_claims(result)
    summary = result.presentation_plan.slides[0]
    assert len(summary.bullet_observation_ids[0]) == 3
    assert len(summary.observation_ids) == 3
    assert result.observations == original
    snapshot = result.model_dump()
    prepare_presentation_claims(result)
    assert result.model_dump() == snapshot


def test_all_eight_topics_without_takeaways_keep_bound_insights_and_provenance():
    result = _topic_result(count=8)
    for topic, theme in zip(result.presentation_topics.topics, result.presentation_plan.themes):
        topic.takeaway = ""
        result.analysis_results.append(AnalysisResult(task_id=topic.id, title=topic.title,
                                                      input_observation_ids=theme.observation_ids))
        result.insights.append(Insight(id="insight-" + topic.id, title=topic.title + " was measured annually.",
                                       narrative="The conclusion covers the reported annual observations.",
                                       kind="reported_fact", result_ids=[topic.id],
                                       evidence=[result.observations[i].evidence[0]
                                                 for i in range(len(result.observations))
                                                 if result.observations[i].id in theme.observation_ids]))
    rebuild_selected_topic_summary(result, result.presentation_plan)
    summary = result.presentation_plan.slides[0]
    assert summary.insight_ids == [item.id for item in result.insights]
    assert summary.bullets == [item.title for item in result.insights]
    assert len(summary.bullet_observation_ids) == 8
    PresentationPlan.model_validate_json(result.presentation_plan.model_dump_json())


def test_old_cached_four_item_summary_restores_omitted_topics_and_per_item_sources():
    result = _topic_result()
    summary = result.presentation_plan.slides[0]
    selected = result.presentation_topics.topics
    summary.bullets = [selected[i].takeaway for i in (0, 1, 2, 5)]
    summary.observation_ids = result.presentation_plan.themes[0].observation_ids[:3]
    # Simulate prior display-only duplicate consolidation in the cache.
    result.presentation_plan.themes[0].observation_ids = summary.observation_ids[:]

    rebuild_selected_topic_summary(result, result.presentation_plan)
    assert summary.bullets == [topic.takeaway for topic in selected]
    assert len(summary.bullet_observation_ids[0]) == 9
    assert summary.source_pages[:3] == [1, 2, 3]
    # A cached/reloaded plan must preserve the expanded references as well.
    result = PipelineResult.model_validate_json(result.model_dump_json())
    before = result.model_dump_json()
    deck = blank_deck()
    _add_planned_summary(deck, result, result.presentation_plan.slides[0], DocumentIndex(result.observations))

    assert [shape.text for shape in _bodies(deck.slides)] == [topic.takeaway for topic in selected]
    assert result.model_dump_json() == before
    _assert_readable_geometry(deck, deck.slides)


def test_sourced_numbers_are_kept_and_an_unsupported_number_does_not_drop_its_topic():
    result = _topic_result(count=2)
    result.presentation_topics.topics[0].takeaway = "Subject A reported 12 in 2025."
    result.presentation_topics.topics[1].takeaway = "Subject B reported 99999 in 2025."
    rebuild_selected_topic_summary(result, result.presentation_plan)
    summary = result.presentation_plan.slides[0]
    assert summary.bullets == ["Subject A reported 12 in 2025.", "Subject B"]
    assert len(summary.bullet_observation_ids) == 2


def test_rebuilding_summary_keeps_repaired_analysis_claims_and_is_idempotent():
    result = _topic_result(count=2)
    current = "Subject A reported 12 in 2025."
    result.presentation_plan.slides.append(PresentationSlide(
        id="analysis", slide_type="analysis", title=current, theme_id="topic-0"))
    result.presentation_topics.topics[1].takeaway = (
        "Subject B is reported across the available annual observations and retains "
        "the measured population and its original source boundaries."
    )
    # A title shortened only for layout should not shorten the summary claim.
    result.presentation_plan.slides.append(PresentationSlide(
        id="analysis-b", slide_type="analysis", title="Subject B", theme_id="topic-1"))
    rebuild_selected_topic_summary(result, result.presentation_plan)
    first = result.presentation_plan.model_dump_json()
    rebuild_selected_topic_summary(result, result.presentation_plan)

    assert result.presentation_plan.model_dump_json() == first
    assert result.presentation_plan.slides[0].bullets == [current, result.presentation_topics.topics[1].takeaway]


def test_rebuilding_does_not_resurrect_a_rejected_long_takeaway_behind_its_short_title():
    result = _topic_result(count=1)
    topic = result.presentation_topics.topics[0]
    topic.takeaway = (
        "Subject A increased its share of the measured population across all the observed "
        "periods while the other subjects declined."
    )
    result.presentation_plan.slides.append(PresentationSlide(
        id="analysis", slide_type="analysis", title=topic.title, theme_id=topic.id,
        selection_reason="The comparative claim was narrowed because its evidence was incompatible."))
    rebuild_selected_topic_summary(result, result.presentation_plan)
    assert result.presentation_plan.slides[0].bullets == [topic.title]


def test_evidence_sync_keeps_repaired_copy_and_adds_newly_bound_sources_once():
    result = _topic_result()
    rebuild_selected_topic_summary(result, result.presentation_plan)
    summary = result.presentation_plan.slides[0]
    summary.bullets[0] = "This approved finding has a narrower scope than the original takeaway."
    texts = summary.bullets[:]
    extra = result.observations[0].model_copy(deep=True)
    extra.id = "newly-bound-reported-share"
    extra.evidence[0].page = 99
    result.observations.append(extra)
    result.presentation_plan.themes[0].observation_ids.append(extra.id)

    assert sync_selected_topic_summary_evidence(result, result.presentation_plan)
    assert summary.bullets == texts
    assert extra.id in summary.bullet_observation_ids[0]
    assert extra.id in summary.observation_ids
    assert 99 in summary.source_pages
    first = result.presentation_plan.model_dump_json()
    assert not sync_selected_topic_summary_evidence(result, result.presentation_plan)
    assert result.presentation_plan.model_dump_json() == first


def test_evidence_sync_does_not_restore_removed_or_reordered_topics():
    result = _topic_result()
    rebuild_selected_topic_summary(result, result.presentation_plan)
    summary = result.presentation_plan.slides[0]
    summary.bullets.reverse()
    summary.bullet_observation_ids.reverse()
    before = result.presentation_plan.model_dump_json()
    assert not sync_selected_topic_summary_evidence(result, result.presentation_plan)
    assert result.presentation_plan.model_dump_json() == before
    summary.bullets.pop()
    summary.bullet_observation_ids.pop()
    before = result.presentation_plan.model_dump_json()
    assert not sync_selected_topic_summary_evidence(result, result.presentation_plan)
    assert result.presentation_plan.model_dump_json() == before


def test_compiler_keeps_six_topics_before_rendering_instead_of_using_a_reference_quota():
    result = _topic_result()
    original = deepcopy(result.observations)
    plan = PresentationPlanRecovery().from_selected_topics(result, origin="topic_compilation")
    summary = next(slide for slide in plan.slides if slide.slide_type == "executive_summary")
    assert summary.bullets == [topic.takeaway for topic in result.presentation_topics.topics]
    assert len(summary.bullet_observation_ids) == 6
    assert result.observations == original
    PresentationPlan.model_validate_json(plan.model_dump_json())


@pytest.mark.parametrize("field,value", [("bullets", ["item"] * 6), ("observation_ids", [f"o{i}" for i in range(41)])])
def test_analysis_slide_keeps_its_single_page_limits(field, value):
    with pytest.raises(ValidationError, match="non-summary slide"):
        PresentationSlide(id="analysis", slide_type="analysis", title="Finding", **{field: value})


def _legacy_repair_plan(result):
    plan = PresentationPlanRecovery().from_selected_topics(result, origin="topic_compilation")
    plan.themes = []
    for slide in plan.slides:
        slide.theme_id = ""
    return plan


def test_legacy_plan_repair_keeps_all_six_summary_bullets_and_their_evidence():
    from adaptive_document_agent.agent.presentation_plan_repairer import PresentationPlanRepairer

    result = _topic_result()
    plan = _legacy_repair_plan(result)
    summary = next(slide for slide in plan.slides if slide.slide_type == "executive_summary")
    before = deepcopy(summary)
    repaired = PresentationPlanRepairer().repair(plan, result)
    summary = next(slide for slide in repaired.slides if slide.slide_type == "executive_summary")

    assert summary.bullets == before.bullets
    assert summary.bullet_observation_ids == before.bullet_observation_ids
    assert set(summary.observation_ids) == set(before.observation_ids)


def test_legacy_summary_repair_filters_text_and_its_exact_evidence_group_together():
    from adaptive_document_agent.agent.presentation_plan_repairer import PresentationPlanRepairer

    result = _topic_result()
    plan = _legacy_repair_plan(result)
    summary = next(slide for slide in plan.slides if slide.slide_type == "executive_summary")
    before = deepcopy(summary)
    summary.bullets[0] = "  "
    # 12 exists elsewhere on the summary, but this bullet only cites 10.
    summary.bullets[1] = "Subject B reported 12."
    summary.bullet_observation_ids[1] = ["subject-1-0-2023"]
    repaired = PresentationPlanRepairer().repair(plan, result)
    summary = next(slide for slide in repaired.slides if slide.slide_type == "executive_summary")

    assert summary.bullets == before.bullets[2:]
    assert summary.bullet_observation_ids == before.bullet_observation_ids[2:]


@pytest.mark.parametrize("copy", ["The finding retains its measured population and source scope. " * 90,
                                 "本项结论保留完整范围限定、已披露期间和原始证据，不补充缺失数据。" * 120], ids=["latin", "cjk"])
def test_compiled_summary_paginates_all_long_topic_copy_with_individual_citations(copy):
    result = _topic_result()
    for topic in result.presentation_topics.topics:
        topic.takeaway = topic.title + ": " + copy
    rebuild_selected_topic_summary(result, result.presentation_plan)
    deck = blank_deck()
    _add_planned_summary(deck, result, result.presentation_plan.slides[0], DocumentIndex(result.observations))

    assert len(deck.slides) > 1
    assert "".join(shape.text for shape in _bodies(deck.slides)) == "".join(topic.takeaway.strip() for topic in result.presentation_topics.topics)
    assert "p. 1-3" in visible(deck.slides[0])
    assert "51-53" not in visible(deck.slides[0])
    _assert_readable_geometry(deck, deck.slides)
