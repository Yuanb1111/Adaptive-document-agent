from adaptive_document_agent.document_model import DocumentIndex, DocumentModelBuilder
from adaptive_document_agent.models import Observation, SourceEvidence


def observation(identifier: str, period: str, value: float, confidence: float = 0.9) -> Observation:
    return Observation(
        id=identifier,
        metric_original="Revenue",
        value=value,
        raw_value=str(value),
        period=period,
        confidence=confidence,
        evidence=[SourceEvidence(page=1, text=str(value), extraction_method="digital_table", confidence=confidence)],
    )


def test_index_queries_metric_and_period() -> None:
    index = DocumentIndex([observation("a", "2024", 100), observation("b", "2025", 120)])
    assert len(index.for_metric("revenue")) == 2
    assert index.for_period("2025")[0].value == 120


def test_builder_keeps_higher_confidence_duplicate_and_merges_evidence() -> None:
    low = observation("low", "2025", 120, 0.5)
    high = observation("high", "2025", 120, 0.9)
    index = DocumentModelBuilder().build([low, high])
    assert len(index.observations) == 1
    assert index.observations[0].id == "high"

