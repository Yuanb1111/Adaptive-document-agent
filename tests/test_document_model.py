from adaptive_document_agent.document_model import DocumentIndex, DocumentModelBuilder, metric_key, metric_label
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


def test_qualified_source_metric_is_not_collapsed_into_broader_canonical_name() -> None:
    amount = Observation(
        id="amount",
        metric_original="Revenue",
        metric_canonical="Revenue",
        value=100,
        raw_value="100",
        unit="currency",
        currency="CNY",
        period="2025",
        confidence=0.9,
    )
    share = Observation(
        id="share",
        metric_original="Revenue: % of Revenue",
        metric_canonical="Revenue",
        value=100,
        raw_value="100%",
        unit="percent",
        period="2025",
        confidence=0.9,
    )

    index = DocumentIndex([amount, share])

    assert metric_label(share) == "Revenue: % of Revenue"
    assert metric_key(amount) != metric_key(share)
    assert index.for_metric("revenue") == [amount]
    assert index.for_metric("revenue: % of revenue") == [share]
