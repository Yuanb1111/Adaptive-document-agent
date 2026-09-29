"""Stock, flow and future facts keep their distinct time bases."""

import pytest

from adaptive_document_agent.models import (
    DocumentPage, Observation, ParsedDocument, PresentationSlide,
    PresentationVisualBlock, SourceEvidence,
)
from adaptive_document_agent.models.presentation import HorizonItem
from adaptive_document_agent.services.presentation_horizon import horizon_data, render_horizon
from tests.test_presentation_brief import blank_deck


def _example():
    text = ("At 31 December 2025, cash was 20 million. During FY2025, operating cash "
            "flow was 5 million. The supplier agreement requires future payments "
            "of 30 million through 2028.")
    document = ParsedDocument(document_id="generic", sha256="x" * 64,
                              safe_filename="source.pdf", page_count=1,
                              pages=[DocumentPage(page_number=1, text=text)])
    stock = Observation(id="cash", metric_original="Cash", value=20,
                        raw_value="20", unit="million", raw_unit="million",
                        period="2025-12-31", period_type="balance_sheet_date",
                        evidence=[SourceEvidence(page=1, text="cash was 20 million",
                                                 extraction_method="digital_text", confidence=.99)],
                        validation_status="valid", confidence=.99)
    flow = Observation(id="flow", metric_original="Operating cash flow", value=5,
                       raw_value="5", unit="million", raw_unit="million",
                       period="FY2025", period_type="fiscal_year",
                       evidence=[SourceEvidence(page=1, text="operating cash flow was 5 million",
                                                extraction_method="digital_text", confidence=.99)],
                       validation_status="valid", confidence=.99)
    block = PresentationVisualBlock(role="horizon", observation_ids=["cash", "flow"],
                                    horizon_items=[
        HorizonItem(kind="stock", label="Cash", text="Cash was 20 million.",
                    source_pages=[1], source_quote="cash was 20 million", observation_id="cash"),
        HorizonItem(kind="flow", label="Operating cash flow", text="Operating cash flow was 5 million.",
                    source_pages=[1], source_quote="operating cash flow was 5 million", observation_id="flow"),
        HorizonItem(kind="future", label="Supplier payments", text="Future payments of 30 million through 2028.",
                    source_pages=[1], source_quote="future payments of 30 million through 2028"),
    ])
    return document, {"cash": stock, "flow": flow}, block


def test_evidence_horizon_renders_three_separate_time_bases():
    document, index, block = _example()
    assert len(horizon_data(block, index, document)) == 3
    plan = PresentationSlide(id="h", slide_type="analysis", title="Resource timing",
                             message="Reported cash, period flow and future payments.",
                             visual_blocks=[block], source_pages=[1])
    slide = render_horizon(blank_deck(), plan, block, index, document)
    assert [shape.text for shape in slide.shapes if shape.name == "horizon:kind"] == [
        "At a date", "During a period", "Future obligation",
    ]
    assert [shape.text for shape in slide.shapes if shape.name == "horizon:value"] == [
        "20 million", "5 million",
    ]
    assert "source_quote" in slide.notes_slide.notes_text_frame.text


def test_horizon_rejects_wrong_time_basis_and_unsourced_number():
    document, index, block = _example()
    index["cash"].period_type = "fiscal_year"
    with pytest.raises(ValueError, match="point-in-time"):
        horizon_data(block, index, document)
    index["cash"].period_type = "balance_sheet_date"
    block.horizon_items[2].text = "Future payments of 40 million through 2028."
    with pytest.raises(ValueError, match="unsupported"):
        horizon_data(block, index, document)
