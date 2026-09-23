from adaptive_document_agent.agent.semantic_resolver import SemanticResolver
from adaptive_document_agent.agent.semantic_resolver import SemanticResolution
from adaptive_document_agent.models.entity import SemanticMapping
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_without_llm_original_terms_are_not_over_normalized() -> None:
    mappings = SemanticResolver().resolve_metrics(["Gross Revenue", "Net Revenue"])
    assert [item.canonical_name for item in mappings] == [None, None]
    assert [item.original_name for item in mappings] == ["Gross Revenue", "Net Revenue"]


def test_period_normalization_is_conservative() -> None:
    assert SemanticResolver.normalize_period("FY 2025") == "2025"
    assert SemanticResolver.normalize_period("Q1 2025") == "Q1 2025"


def test_empty_metrics_do_not_call_model():
    gateway = Mock()
    assert SemanticResolver(gateway).resolve_metrics(["", "  "]) == []
    gateway.generate_structured.assert_not_called()


def test_parallel_batches_keep_order_vocabulary_context_and_all_terms():
    names = [f"Metric {i}" for i in range(120)]
    barrier, lock = Barrier(3), Lock()
    active = peak = 0

    def generate(messages, response_model, **kwargs):
        nonlocal active, peak
        text = messages[-1]["content"]
        assert "source context" in text
        assert all(name in text for name in names)
        assert kwargs["stage"] == "semantic"
        assigned = [line[2:] for line in text.splitlines() if line.startswith("- Metric ")]
        assert len(assigned) <= 48
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=5)
        with lock:
            active -= 1
        return SemanticResolution(mappings=[
            SemanticMapping(original_name=name, canonical_name=None, confidence=.5)
            for name in reversed(assigned)
        ])

    gateway = SimpleNamespace(discovery_workers=3, generate_structured=generate)
    result = SemanticResolver(gateway).resolve_metrics(names + [names[0]], context="source context")
    assert [item.original_name for item in result] == names
    assert peak == 3


def test_serial_client_keeps_single_request_for_large_vocabulary():
    gateway = SimpleNamespace(discovery_workers=1, generate_structured=Mock(return_value=SemanticResolution()))
    result = SemanticResolver(gateway).resolve_metrics([f"M{i}" for i in range(100)])
    assert len(result) == 100
    assert all(item.confidence == 0 and item.canonical_name is None for item in result)
    assert gateway.generate_structured.call_count == 1


def test_parallel_failure_does_not_return_partial_mappings():
    gateway = SimpleNamespace(discovery_workers=4, generate_structured=Mock(side_effect=ValueError("failed")))
    with pytest.raises(ValueError, match="failed"):
        SemanticResolver(gateway).resolve_metrics([f"M{i}" for i in range(100)])
