from adaptive_document_agent.agent.semantic_resolver import SemanticResolver


def test_without_llm_original_terms_are_not_over_normalized() -> None:
    mappings = SemanticResolver().resolve_metrics(["Gross Revenue", "Net Revenue"])
    assert [item.canonical_name for item in mappings] == [None, None]
    assert [item.original_name for item in mappings] == ["Gross Revenue", "Net Revenue"]


def test_period_normalization_is_conservative() -> None:
    assert SemanticResolver.normalize_period("FY 2025") == "2025"
    assert SemanticResolver.normalize_period("Q1 2025") == "Q1 2025"

