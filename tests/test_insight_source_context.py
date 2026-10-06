"""A child row must not lose its parent meaning between analysis and prose."""

import copy
import json

import pytest

from adaptive_document_agent.agent.insight_generator import InsightGenerator, InsightList
from adaptive_document_agent.agent.report_generator import ReportGenerator
from adaptive_document_agent.models import (
    AnalysisResult, DocumentProfile, Insight, Observation, ReportPlan, ReportSection, SourceEvidence,
)
from adaptive_document_agent.validation.insight_context import validate_insight_contexts


def sample(parent="Grants allocated to", child="Research", category=None):
    evidence = SourceEvidence(page=2, table_id="t", row_label=child, text="14", extraction_method="table", confidence=.9)
    item = Observation(id="o", metric_original=child, raw_value="14", value=14, parent_section=parent,
                       category_dimensions=category or {}, evidence=[evidence], confidence=.9)
    result = AnalysisResult(task_id="r", title=child, result=14, input_observation_ids=["o"],
                            evidence=[evidence], confidence=.9)
    insight = Insight(id="i", title=child, narrative=f"{child} stood at 14.", kind="reported_fact", result_ids=["r"])
    return item, result, insight


@pytest.mark.parametrize("parent,child", [
    ("Grants allocated to", "Research"),
    ("Rejected batches", "Water treatment"),
    ("Survey respondents preferring", "Remote work"),
    ("试验退出原因", "药物反应"),
])
def test_parent_scope_omission_is_withheld_across_domains(parent, child):
    item, result, insight = sample(parent, child)
    raw = copy.deepcopy(item)
    accepted, issues = validate_insight_contexts([insight], [result], [item])
    assert accepted == []
    assert json.loads(issues[0].message)["insight"]["narrative"] == insight.narrative
    assert issues[0].evidence == item.evidence
    assert item == raw
    insight.narrative = f"{parent}: {child} stood at 14."
    assert validate_insight_contexts([insight], [result], [item]) == ([insight], [])


def test_category_scope_cannot_be_in_hidden_metadata_only():
    item, result, insight = sample(None, "Satisfaction", {"cohort": "Remote staff"})
    insight.title = "Remote staff satisfaction"
    insight.metric = "Remote staff: Satisfaction"
    assert not validate_insight_contexts([insight], [result], [item])[0]
    insight.narrative = "Remote staff satisfaction stood at 14."
    assert validate_insight_contexts([insight], [result], [item])[0] == [insight]


def test_gateway_receives_parent_identity_and_fallback_cannot_repeat_bad_prose():
    item, result, insight = sample()
    insight.narrative = "Research expense stood at 14."
    captured = {}

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            captured["payload"] = messages[-1]["content"]
            return InsightList(insights=[insight])

    generator = InsightGenerator(Gateway())
    accepted = generator.generate([result], [item])
    assert '"parent_section": "Grants allocated to"' in captured["payload"]
    assert '"qualified_metric_label": "Grants allocated to: Research"' in captured["payload"]
    assert "Grants allocated to: Research" in accepted[0].narrative
    assert "Research expense" not in accepted[0].narrative
    assert generator.validation_issues
    assert "Research expense" in generator.validation_issues[0].message


def test_markdown_does_not_republish_rejected_audit_draft():
    item, result, insight = sample()
    insight.narrative = "Invented expense explanation."
    accepted, issues = validate_insight_contexts([insight], [result], [item])
    markdown = ReportGenerator().generate(
        DocumentProfile(document_type="Study", document_purpose="Compare outcomes"),
        ReportPlan(sections=[ReportSection(title="Findings", purpose="Review", insight_ids=["i"])]),
        accepted, issues,
    )
    assert "Invented expense" not in markdown
    assert "omitted the source metric's parent or category scope" in markdown
    assert "Invented expense" in issues[0].message


def test_unscoped_sources_and_existing_result_only_callers_remain_supported():
    item, result, insight = sample(None)
    assert validate_insight_contexts([insight], [result], [item]) == ([insight], [])
    assert InsightGenerator().generate([result])[0].title == result.title
