"""Recovered source hierarchy must reach findings, not only observation metadata."""

from adaptive_document_agent.agent.insight_generator import InsightGenerator
from adaptive_document_agent.extraction.comparison_context import restore_comparison_context
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models import AnalysisResult, Insight
from adaptive_document_agent.validation.insight_context import validate_insight_contexts
from tests.test_source_heading_scope import source_table


def test_recovered_group_withholds_old_unqualified_finding_and_qualifies_fallback():
    table = source_table("Current", "Amounts due to counterparties non-trade")
    table.raw_header_lines.append("Amounts due to counterparties")
    table.rows[1].cells[0] = "Interest-bearing bank loans"
    selected = [item for item in ObservationExtractor()._table_observations(table)
                if item.row_id == 1]
    stale = [item.model_copy(update={"parent_section": None, "dimensions": {}})
             for item in selected]
    original = [item.model_dump() for item in stale]
    restored = restore_comparison_context(stale, [table])
    calculation = AnalysisResult(
        task_id="loan-change", title="Interest-bearing bank loans change",
        result=1, input_observation_ids=[item.id for item in restored],
        evidence=[source for item in restored for source in item.evidence], confidence=.9,
    )
    draft = Insight(
        id="old-finding", title="Bank loans increased",
        narrative="Interest-bearing bank loans increased from 8 to 9.",
        kind="interpretation",
        result_ids=[calculation.task_id], evidence=calculation.evidence,
        confidence=.9, importance=.8,
    )

    accepted, issues = validate_insight_contexts([draft], [calculation], restored)
    assert accepted == []
    assert [issue.code for issue in issues] == ["insight_source_context"]
    assert "Current" in issues[0].message
    assert draft.narrative in issues[0].message  # Rejected prose remains auditable.
    assert [item.model_dump() for item in stale] == original

    fallback, = InsightGenerator().generate([calculation], restored)
    assert "Current: Interest-bearing bank loans" in fallback.narrative
    assert fallback.evidence == calculation.evidence
    assert not validate_insight_contexts([fallback], [calculation], restored)[1]
