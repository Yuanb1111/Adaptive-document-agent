from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor


class FakePage:
    def extract_text(self, **_: object) -> str:
        return """FINANCIAL INFORMATION
RESULTS OF OPERATIONS
Year ended December 31, Six months ended June 30,
2021 2022 2023 2023 2024
% of % of % of % of % of
Amount Revenue Amount Revenue Amount Revenue Amount Revenue Amount Revenue
(RMB in thousands, except for percentages)
Revenue ........ 174,314 100.0 241,013 100.0 286,749 100.0 109,912 100.0 120,462 100.0
Gross profit .... 88,080 50.5 98,217 40.8 124,844 43.5 42,934 39.1 52,844 43.9
"""


class SingleRowPage:
    def extract_text(self, **_: object) -> str:
        return """TURNOVER DAYS
Year ended December 31, Six months ended June 30,
2021 2022 2023 2024
Trade payables turnover days ........ 88 62 69 81
"""


class VerticalPeriodPage:
    def extract_text(self, **_: object) -> str:
        return """SENSITIVITY ANALYSIS
Increase in basis points  Profit before tax  Equity
Year ended December 31, 2022
If currency weakens ........ 5 2,367 2,367
If currency strengthens .... 5 (2,367) (2,367)
Year ended December 31, 2023
If currency weakens ........ 5 3,357 3,357
If currency strengthens .... 5 (3,357) (3,357)
"""


class WrappedFirstRowPage:
    def extract_text(self, **_: object) -> str:
        return """CASH FLOW
Year ended December 31, Six months ended June 30,
2021 2022 2023 2023 2024
(RMB in thousands)
Operating loss before changes in
working capital ........ (25,801) (15,177) (19,708) (22,108) (26,472)
Working capital changes . 32,168 (100,487) (99,537) (56,164) (30,356)
"""


def test_borderless_financial_grid_preserves_period_basis_units_and_measures() -> None:
    tables = BorderlessTableExtractor().extract(FakePage(), 309)
    assert len(tables) == 1
    table = tables[0]
    assert table.column_periods[1:] == [
        "FY2021",
        "FY2021",
        "FY2022",
        "FY2022",
        "FY2023",
        "FY2023",
        "6M2023",
        "6M2023",
        "6M2024",
        "6M2024",
    ]
    assert table.headers[1:3] == ["Amount", "% of Revenue"]
    assert table.context_label == "RESULTS OF OPERATIONS"
    observations = ObservationExtractor()._table_observations(table)
    revenue_amounts = [item for item in observations if item.metric_original == "Revenue"]
    revenue_percentages = [item for item in observations if item.metric_original == "Revenue: % of Revenue"]
    assert len(revenue_amounts) == 5
    assert len(revenue_percentages) == 5
    assert revenue_amounts[0].value == 174_314_000
    assert revenue_amounts[0].currency == "CNY"
    assert revenue_amounts[0].unit_scale == 1_000
    assert revenue_amounts[0].raw_unit == "RMB in thousands"
    assert revenue_amounts[0].dimensions["period_basis"] == "FY"
    assert revenue_percentages[0].value == 100.0
    assert revenue_percentages[0].unit == "percent"


def test_apostrophe_thousands_declaration_is_preserved() -> None:
    class ApostropheUnitPage:
        def extract_text(self, **_: object) -> str:
            return """FINANCIAL DATA
Year ended December 31,
2023 2024
(RMB’000)
Revenue ........ 10,000 12,000
Gross profit .... 4,000 5,000
"""

    table = BorderlessTableExtractor().extract(ApostropheUnitPage(), 8)[0]
    observations = ObservationExtractor()._table_observations(table)
    revenue = next(item for item in observations if item.metric_original == "Revenue")
    assert revenue.currency == "CNY"
    assert revenue.unit_scale == 1_000
    assert revenue.value == 10_000_000
    assert revenue.raw_unit == "RMB’000"


def test_collapsed_headers_preserve_full_year_and_interim_periods_and_nearest_scale() -> None:
    class CollapsedHeaderPage:
        def extract_text(self, **_: object) -> str:
            return """FINANCIAL INFORMATION
Revenue was RMB174.3 million in an earlier narrative sentence.
YearendedDecember31, SixmonthsendedJune30,
2021 2022 2023 2023 2024
%of %of %of %of %of
Amount Revenue Amount Revenue Amount Revenue Amount Revenue Amount Revenue
(RMBinthousands,exceptforpercentages)
Revenue ........ 174,314 100.0 241,013 100.0 286,749 100.0 109,912 100.0 120,462 100.0
Gross profit .... 88,080 50.5 98,217 40.8 124,844 43.5 42,934 39.1 52,844 43.9
"""

    table = BorderlessTableExtractor().extract(CollapsedHeaderPage(), 9)[0]
    assert table.column_periods[1:] == [
        "FY2021", "FY2021", "FY2022", "FY2022", "FY2023", "FY2023", "6M2023", "6M2023", "6M2024", "6M2024"
    ]
    assert table.default_currency == "CNY"
    assert table.default_unit_scale == 1_000
    observations = ObservationExtractor()._table_observations(table)
    amounts = [item for item in observations if item.metric_original == "Revenue"]
    assert [item.period for item in amounts] == ["FY2021", "FY2022", "FY2023", "6M2023", "6M2024"]
    assert all(item.unit == "currency" and item.currency == "CNY" for item in amounts)
    assert all(item.dimensions["table_context"] == "FINANCIAL INFORMATION" for item in amounts)


def test_repeated_as_of_years_keep_exact_reporting_dates() -> None:
    class RepeatedAsOfPage:
        def extract_text(self, **_: object) -> str:
            return """CURRENT ASSETS
As of As of
As of December 31,
June 30, October 31,
2021 2022 2023 2024 2024
(RMB in thousands)
Inventories ........ 70,901 131,843 141,520 155,296 157,903
Cash and cash equivalents ........ 149,093 297,763 110,962 73,033 81,324
"""

    table = BorderlessTableExtractor().extract(RepeatedAsOfPage(), 10)[0]
    assert table.column_periods[1:] == ["2021-12-31", "2022-12-31", "2023-12-31", "2024-06-30", "2024-10-31"]


def test_split_interim_header_still_distinguishes_duplicate_year() -> None:
    class SplitInterimPage:
        def extract_text(self, **_: object) -> str:
            return """KEY RATIOS
As of/for the six months
As of/for the year ended December 31, ended June 30,
2021 2022 2023 2023 2024
Gross profit margin ........ 50.5% 40.8% 43.5% 39.1% 43.9%
Current ratio ........ 2.9 2.2 3.1 2.7 2.8
"""

    table = BorderlessTableExtractor().extract(SplitInterimPage(), 11)[0]
    assert table.column_periods[1:] == ["FY2021", "FY2022", "FY2023", "6M2023", "6M2024"]


def test_narrative_year_is_not_reused_as_a_table_value() -> None:
    assert BorderlessTableExtractor._parse_row(0, "procurement increased in 2022 2022 (2)") is None


def test_single_row_borderless_table_is_kept_when_period_headers_support_it() -> None:
    tables = BorderlessTableExtractor().extract(SingleRowPage(), 1)
    assert len(tables) == 1
    assert tables[0].rows[0].cells[0] == "Trade payables turnover days"
    # This text-only fixture contains both annual and interim headings, but no
    # coordinates locating their boundary. Keep the row, never invent all-FY.
    assert tables[0].column_periods[1:] == [None] * 4
    assert any("ambiguous" in warning for warning in tables[0].warnings)


def test_vertical_period_groups_preserve_row_specific_periods() -> None:
    table = BorderlessTableExtractor().extract(VerticalPeriodPage(), 1)[0]
    observations = ObservationExtractor()._table_observations(table)
    assert {item.period for item in observations} == {"FY2022", "FY2023"}


def test_wrapped_first_data_label_is_not_mistaken_for_column_headers() -> None:
    table = BorderlessTableExtractor().extract(WrappedFirstRowPage(), 1)[0]
    assert all(header.startswith("column_") for header in table.headers[1:])
    metrics = {item.metric_original for item in ObservationExtractor()._table_observations(table)}
    assert "Operating loss before changes in working capital" in metrics
    assert "Operating" not in metrics


def test_cid_dot_leaders_do_not_destroy_financial_period_series() -> None:
    class CidLeaderPage:
        def extract_text(self, **_: object) -> str:
            return """FINANCIAL INFORMATION
RESULTS OF OPERATIONS
Year ended December 31,
2023 2024 2025
% of % of % of
Amount Revenue Amount Revenue Amount Revenue
(RMB in thousands, except for percentages)
Revenue (cid:2) (cid:2) (cid:2) 267,025 100.0 325,257 100.0 521,747 100.0
Cost of revenue (cid:2) (cid:2) (236,454) (88.6) (254,065) (78.1) (407,579) (78.1)
Gross profit (cid:2) (cid:2) 30,571 11.4 71,192 21.9 114,168 21.9
Listing expenses (cid:2) (cid:2) �C �C �C �C (15,356) (2.9)
"""

    table = BorderlessTableExtractor().extract(CidLeaderPage(), 234)[0]

    assert table.column_periods[1:] == ["FY2023", "FY2023", "FY2024", "FY2024", "FY2025", "FY2025"]
    assert table.headers[1:3] == ["Amount", "% of Revenue"]
    assert [row.cells[0] for row in table.rows] == ["Revenue", "Cost of revenue", "Gross profit", "Listing expenses"]
    assert table.rows[-1].cells[1:] == ["—", "—", "—", "—", "(15,356)", "(2.9)"]

    observations = ObservationExtractor()._table_observations(table)
    revenue = [item for item in observations if item.metric_original == "Revenue"]
    assert [item.period for item in revenue] == ["FY2023", "FY2024", "FY2025"]
    assert [item.value for item in revenue] == [267_025_000, 325_257_000, 521_747_000]
    percentages = [item for item in observations if item.metric_original == "Revenue: % of Revenue"]
    assert len({item.id for item in percentages}) == 3


def test_repeated_multiline_measure_headers_are_reconstructed() -> None:
    class GeographicMarginPage:
        def extract_text(self, **_: object) -> str:
            return """FINANCIAL INFORMATION
Year ended December 31,
2023 2024 2025
Gross profit Gross profit Gross profit
Gross profit margin Gross profit margin Gross profit margin
(RMB in thousands, except for percentages)
Mainland 28,991 12.7% 65,837 22.2% 98,471 20.73%
Overseas market 16,064 42.1% 13,567 46.4% 21,969 47.12%
"""

    table = BorderlessTableExtractor().extract(GeographicMarginPage(), 239)[0]

    assert table.headers[1:] == [
        "Gross profit", "Gross profit margin",
        "Gross profit", "Gross profit margin",
        "Gross profit", "Gross profit margin",
    ]
    observations = ObservationExtractor()._table_observations(table)
    assert {item.metric_original for item in observations} == {"Gross profit", "Gross profit margin"}
    assert {item.dimensions["category"] for item in observations} == {"Mainland", "Overseas market"}
