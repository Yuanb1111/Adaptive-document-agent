import pytest

from adaptive_document_agent.tools import create_default_registry
from adaptive_document_agent.tools.safe_formula import evaluate_formula


def test_core_calculations() -> None:
    tools = create_default_registry()
    assert tools.execute("absolute_change", start=100, end=120) == 20
    assert tools.execute("percentage_change", start=100, end=120) == pytest.approx(20)
    assert tools.execute("cagr", start=100, end=121, periods=2) == pytest.approx(10)
    assert tools.execute("ratio", numerator=400, denominator=1000) == pytest.approx(0.4)
    assert tools.execute("contribution_share", values=[40, 30, 30]) == pytest.approx([40, 30, 30])
    assert tools.execute("mean", values=[1, 2, 3]) == 2
    assert tools.execute("median", values=[1, 100, 2]) == 2
    assert tools.execute("linear_trend", values=[1, 2, 3])["direction"] == "increasing"
    assert tools.execute("pearson_correlation", left=[1, 2, 3, 4, 5], right=[2, 4, 6, 8, 10]) == pytest.approx(1)


def test_statistical_minimums_and_zero_denominator() -> None:
    tools = create_default_registry()
    with pytest.raises(ValueError):
        tools.execute("pearson_correlation", left=[1, 2], right=[1, 2])
    with pytest.raises(ValueError):
        tools.execute("ratio", numerator=1, denominator=0)


def test_non_monotonic_trend_is_not_described_as_simply_decreasing() -> None:
    tools = create_default_registry()
    result = tools.execute("linear_trend", values=[88, 62, 69, 81])
    assert result["direction"] == "mixed"
    assert result["turning_points"] == 1


def test_safe_formula_allows_arithmetic_only() -> None:
    assert evaluate_formula("gross_profit / revenue", {"gross_profit": 400, "revenue": 1000}) == pytest.approx(0.4)
    with pytest.raises(ValueError):
        evaluate_formula("__import__('os').system('whoami')", {})
