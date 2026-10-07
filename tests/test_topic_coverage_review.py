"""Editorial coverage is model-adjudicated across arbitrary metric vocabularies."""

import json

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.agent.topic_coverage_review import TopicCoverageReview, source_period_views
from adaptive_document_agent.models import Observation, PresentationTopic, PresentationTopicSelection, SourceEvidence
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName
from tests.test_pptx_export import _result


def _observation(metric, period, value, *, basis="FY", definition="UNSPECIFIED", page=234):
    return Observation(id=f"{metric}-{period}-{definition}", metric_original=metric, raw_value=str(value),
        value=value, period=period, unit="count", raw_unit="units", unit_scale=1,
        period_basis=basis, period_type="fiscal_year" if basis == "FY" else "interim_flow",
        ifrs_status=definition, entity="Sample", table_id="source", row_id=1,
        evidence=[SourceEvidence(page=page, table_id="source", row_label=metric,
            text=f"{metric} {period} {value}", extraction_method="digital_table", confidence=.95)],
        confidence=.95)


def _topic(sid, identifier="history"):
    return PresentationTopic(id=identifier, title="Reported performance", question="How did the reported measure move?",
        rationale="Comparable reported observations support this question.", series_ids=[sid])


def _fixture(metric="Output", counterpoint="Waste"):
    result = _result()
    result.profile.document_type = "Operational review"
    result.profile.document_purpose = "Assess performance and constraints."
    result.profile.analysis_focus = "Operations"
    result.insights = []
    result.observations = [
        _observation(metric, "FY2022", 100), _observation(metric, "FY2023", 200),
        _observation(metric, "6M2023", 90, basis="6M"), _observation(metric, "6M2024", 70, basis="6M"),
        _observation(counterpoint, "FY2022", 20), _observation(counterpoint, "FY2023", 60),
    ]
    directory, lookup = series_directory(result)
    annual = next(d["id"] for d in directory if d["metric"] == metric and d["periods"][0].startswith("FY"))
    interim = next(d["id"] for d in directory if d["metric"] == metric and d["periods"][0].startswith("6M"))
    adverse = next(d["id"] for d in directory if d["metric"] == counterpoint)
    return result, directory, lookup, annual, interim, adverse


def _review(annual, interim, adverse):
    return TopicCoverageReview(topics=[_topic(annual), _topic(interim, "current"), _topic(adverse, "counterpoint")],
        coverage_decisions=[
            {"series_id": interim, "decision": "include", "reason": "The recent matched duration changes the historical interpretation."},
            {"series_id": adverse, "decision": "include", "reason": "This outcome qualifies the selected activity measure."},
        ])


@pytest.mark.parametrize(("metric", "counterpoint"), [
    ("Output", "Waste"), ("Satisfaction", "Turnover intention"), ("Gross margin", "Net result"),
])
def test_model_can_restore_material_counterpoint_and_recent_comparison(metric, counterpoint):
    result, _, _, annual, interim, adverse = _fixture(metric, counterpoint)
    raw = [o.model_dump() for o in result.observations]
    draft = PresentationTopicSelection(topics=[_topic(annual)], omissions=[
        {"series_id": adverse, "reason": "Secondary measure."}])
    responses = [draft.model_dump(), _review(annual, interim, adverse).model_dump()]
    client = MockLLMClient(responses)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.OLLAMA, model="local",
        base_url="http://127.0.0.1:11434", privacy_mode=PrivacyMode.LOCAL_ONLY))
    selection = PresentationTopicSelector(gateway).select(result)
    assert len(client.calls) == 2
    assert {sid for t in selection.topics for sid in t.series_ids} == {annual, interim, adverse}
    payload = json.loads(client.calls[1][-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert set(payload["series_requiring_coverage_decision"]) == {interim, adverse}
    assert len(payload["same_source_row_period_views"]) == 1
    points_position = payload["series_columns"].index("reported_points")
    rows = {row[0]: row[points_position] for row in payload["all_extracted_series"]}
    assert [point[1:4] for point in rows[interim]] == [["6M2023", "90", 90], ["6M2024", "70", 70]]
    assert [o.model_dump() for o in result.observations] == raw
    assert any(w.code == "presentation_topic_coverage_review" for w in result.validation_warnings)


def test_model_may_explicitly_keep_omissions_without_forced_metric_selection():
    result, _, _, annual, interim, adverse = _fixture()
    review = TopicCoverageReview(topics=[_topic(annual)], coverage_decisions=[
        {"series_id": sid, "decision": "omit", "reason": "The requested question is confined to the annual operating scope."}
        for sid in (interim, adverse)])
    client = MockLLMClient([{"topics": [_topic(annual).model_dump()]}, review.model_dump()])
    selection = PresentationTopicSelector(LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))).select(result)
    assert [t.series_ids for t in selection.topics] == [[annual]]
    assert {o.series_id for o in selection.omissions} == {interim, adverse}
    audit = json.loads(next(w.message for w in result.validation_warnings if w.code == "presentation_topic_coverage_review"))
    assert len(audit["review"]["coverage_decisions"]) == 2


@pytest.mark.parametrize("fault", ["missing_decision", "false_inclusion", "unknown_series", "lost_original", "unsupported_number"])
def test_bad_coverage_review_is_transactional_and_not_retried(fault):
    result, _, _, annual, interim, adverse = _fixture()
    draft = PresentationTopicSelection(topics=[_topic(annual)])
    review = _review(annual, interim, adverse)
    if fault == "missing_decision":
        review.coverage_decisions.pop()
    elif fault == "false_inclusion":
        review.topics = [_topic(annual)]
    elif fault == "unknown_series":
        review.topics[-1].series_ids = ["invented"]
    elif fault == "lost_original":
        review.topics.pop(0)
    else:
        review.topics[-1].takeaway = "Result reached 999999."
    client = MockLLMClient([draft.model_dump(), review.model_dump()])
    selected = PresentationTopicSelector(LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))).select(result)
    assert selected == draft
    assert len(client.calls) == 2
    warning = next(w for w in result.validation_warnings if w.code == "presentation_topic_coverage_unresolved")
    assert json.loads(warning.message)["rejected_review"] is not None


def test_review_transport_failure_preserves_selection_and_records_unresolved_coverage():
    result, _, _, annual, _, _ = _fixture()
    draft = PresentationTopicSelection(topics=[_topic(annual)])
    client = MockLLMClient([draft.model_dump()])
    selected = PresentationTopicSelector(LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))).select(result)
    assert selected == draft
    assert len(client.calls) == 2
    assert any(w.code == "presentation_topic_coverage_unresolved" for w in result.validation_warnings)
    from adaptive_document_agent.agent.topic_coverage_review import coverage_review_pending
    from adaptive_document_agent.services.presentation_editorial import review_presentation, stamp_editorial_review
    from adaptive_document_agent.models import PresentationPlan
    result.presentation_topics = selected
    plan = PresentationPlan(title="Review", planning_origin="topic_compilation")
    assert coverage_review_pending(result)
    assert any(f.code == "presentation_topic_coverage_unresolved" for f in review_presentation(plan, result))
    assert stamp_editorial_review(plan, result, origin="topic_compilation").editorial_status == "needs_review"
    _, lookup = series_directory(result)
    result.presentation_topics = PresentationTopicSelection(topics=[_topic(sid, sid) for sid in lookup])
    assert not coverage_review_pending(result)
    assert stamp_editorial_review(plan, result, origin="topic_compilation").editorial_status == "ready"


def test_oversized_review_does_not_sample_away_counterevidence(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review
    monkeypatch.setattr(topic_coverage_review, "MAX_REVIEW_CHARACTERS", 20)
    result, _, _, annual, _, _ = _fixture()
    draft = PresentationTopicSelection(topics=[_topic(annual)])
    client = MockLLMClient([draft.model_dump()])
    selected = PresentationTopicSelector(LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))).select(result)
    assert selected == draft and len(client.calls) == 1
    assert any("silently sampled" in w.message for w in result.validation_warnings)


def test_period_view_links_require_exact_source_and_definition_scope():
    result, _, lookup, annual, interim, _ = _fixture()
    assert len(source_period_views(lookup)) == 1
    for item in lookup[interim]:
        item.ifrs_status = "ADJUSTED"
    assert source_period_views(lookup) == []
    for item in lookup[interim]:
        item.ifrs_status = "UNSPECIFIED"
        item.period = "unknown"
    views = source_period_views(lookup)
    entries = {item["series_id"]: item for item in views[0]["same_source_row"]}
    assert entries[annual]["internally_comparable_periods"] is True
    assert entries[interim]["internally_comparable_periods"] is False


def test_series_inventory_preserves_interior_points_and_definition_metadata():
    result, _, _, _, _, _ = _fixture()
    result.observations.append(_observation("Output", "FY2024", 80))
    entry = next(item for item in series_directory(result)[0]
                 if item["metric"] == "Output" and item["periods"][0].startswith("FY"))
    assert [point[3] for point in entry["reported_points"]] == [100, 200, 80]
    assert all(point[4:7] == [1, "FY", "fiscal_year"] for point in entry["reported_points"])
    assert all(point[-1] == [234] for point in entry["reported_points"])
