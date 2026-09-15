import pytest

from adaptive_document_agent.extraction.numeric_parser import parse_number


@pytest.mark.parametrize(
    ("raw", "value", "unit", "currency"),
    [
        ("1,250", 1250, None, None),
        ("1.25m", 1_250_000, None, None),
        ("$2.4 billion", 2_400_000_000, "currency", "USD"),
        ("(500)", -500, None, None),
        ("18.2%", 18.2, "percent", None),
        ("£4.5m", 4_500_000, "currency", "GBP"),
        ("120 bps", 120, "basis_points", None),
        ("RMB 3.2bn", 3_200_000_000, "currency", "CNY"),
    ],
)
def test_supported_formats(raw: str, value: float, unit: str | None, currency: str | None) -> None:
    parsed = parse_number(raw)
    assert parsed is not None
    assert parsed.value == pytest.approx(value)
    assert parsed.unit == unit
    assert parsed.currency == currency


def test_missing_value_is_not_invented() -> None:
    assert parse_number("N/A") is None
    assert parse_number("not reported") is None

