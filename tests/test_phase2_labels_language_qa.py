from __future__ import annotations

import pytest

from adaptive_document_agent.agent.insight_generator import InsightGenerator
from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric,
    sanitize_metric_label,
)
from adaptive_document_agent.models import AnalysisResult, SourceEvidence
from adaptive_document_agent.services.financial_formatter import shorten_metric_title
from adaptive_document_agent.services.language_qa import clean_metric_label, clean_presentation_text
from adaptive_document_agent.services.pptx_export import _summary_text


def test_metric_label_mappings() -> None:
    """Ensure verbose database and accounting names are mapped to standard institutional presentation labels."""
    cases = [
        ("Research and development expenses: share of revenue", "R&D / Revenue"),
        ("Research and development expense: share of revenue", "R&D / Revenue"),
        ("Research and development expenses (as % of revenue)", "R&D / Revenue"),
        ("Selling and distribution expenses: share of revenue", "Selling & Distribution / Revenue"),
        ("Selling and marketing expenses: share of revenue", "Selling & Marketing / Revenue"),
        ("Administrative expenses: share of revenue", "Admin / Revenue"),
        ("Cost of sales: share of revenue", "Cost of Sales / Revenue"),
        ("Cost of revenue: share of revenue", "Cost of Sales / Revenue"),
        ("Selling, general and administrative expenses: share of revenue", "SG&A / Revenue"),
        ("Warehouse fulfillment expenses: share of revenue", "Warehouse Fulfillment / Revenue"),
    ]
    for raw_name, expected in cases:
        assert clean_metric_label(raw_name) == expected, f"Failed for {raw_name}"
        assert sanitize_metric_label(raw_name).casefold() == expected.casefold(), f"sanitize_metric_label failed for {raw_name}"
        assert shorten_metric_title(raw_name) == expected, f"shorten_metric_title failed for {raw_name}"


def test_metric_labels_no_mechanical_ellipsis() -> None:
    """Never generate labels ending with mechanical ellipses."""
    raw_long = "Research and development expenses: share of revenue..."
    clean = clean_metric_label(raw_long)
    assert not clean.endswith("...")
    assert not clean.endswith("…")
    assert clean == "R&D / Revenue"

    # Test shortening with max_length strictly prevents ellipsis
    shortened = clean_metric_label("Property, plant and equipment valuation and impairment charges", max_length=30)
    assert not shortened.endswith("...")
    assert not shortened.endswith("…")
    assert len(shortened) <= 30


def test_summary_text_no_ellipsis_by_default() -> None:
    """_summary_text in pptx_export should not mechanically append '...' by default for labels and headers."""
    text = "Warehouse fulfillment services revenue contribution"
    res = _summary_text(text, maximum=25)
    assert not res.endswith("...")
    assert len(res) <= 25

    # If explicitly requested for narrative paragraphs, allow_ellipsis works
    res_with_ellipsis = _summary_text(text, maximum=25, allow_ellipsis=True)
    assert res_with_ellipsis.endswith("...")


def test_language_qa_fixes_ocr_and_prompt_leaks() -> None:
    """Language QA must fix common OCR glitches, double negatives, and prompt leaks in presentation text."""
    # OCR typo fixes
    assert clean_presentation_text("Gross profit from fulfient operations") == "Gross profit from fulfillment operations"
    assert clean_presentation_text("Current liabilties and receviables") == "Current liabilities and receivables"
    assert clean_presentation_text("Annual depreciaton and amoritization") == "Annual depreciation and amortization"
    assert clean_presentation_text("Unaudtied interim fianncial report") == "Unaudited interim financial report"

    # Double negatives
    assert clean_presentation_text("Operating margin increased by -2.5 pp") == "Operating margin decreased by 2.5 pp"
    assert clean_presentation_text("Net loss widened by -15.0m") == "net loss narrowed by 15.0m"

    # Prompt leaks
    assert "Analysis indicates" in clean_presentation_text("Calculated change result: Revenue grew by 12%")
    assert "reported data" in clean_presentation_text("Based on retained facts from Note 4")

    # Duplicate words
    assert clean_presentation_text("The group achieved strong growth in in the the segment") == "The group achieved strong growth in the segment"


def test_structured_analytical_depth() -> None:
    """Keep supported metric/movement without fabricating the optional depth fields."""
    ev = SourceEvidence(page=12, text="Operating margin contracted 1.2 pp", extraction_method="digital_table", confidence=0.9)
    result = AnalysisResult(
        task_id="task_op_margin",
        title="Operating profit margin",
        result="14.2%",
        confidence=0.88,
        evidence=[ev],
    )
    generator = InsightGenerator(gateway=None)
    insights = generator.generate([result])

    assert len(insights) == 1
    insight = insights[0]

    assert insight.metric == "Operating Margin"
    assert insight.movement is not None and "14.2%" in insight.movement
    assert insight.driver is None
    assert insight.implication is None
    assert insight.watch_item is None
    assert "Management did not disclose" not in insight.narrative
    assert "liquidity" not in insight.narrative
