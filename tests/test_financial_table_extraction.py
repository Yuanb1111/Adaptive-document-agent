from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models.table import ExtractedTable, TableRow


def test_repeated_period_groups_do_not_turn_currency_into_metrics() -> None:
    raw = [
        ["Products", "$", "307,003", "$", "294,866", "$", "298,085"],
        ["Services", "109,158", None, "96,169", None, "85,200", None],
        ["Total net sales", "$", "416,161", "$", "391,035", "$", "383,285"],
    ]
    table = ExtractedTable(
        table_id="sales",
        page=32,
        headers=["label", "column_2", "column_3", "column_4", "column_5", "column_6", "column_7"],
        column_periods=[None, "2025", "2025", "2024", "2024", "2023", "2023"],
        rows=[TableRow(cells=row, page=32) for row in raw],
        raw_cells=raw,
        confidence=0.9,
        default_unit="currency",
        default_unit_scale=1_000_000,
        default_currency="USD",
    )
    observations = ObservationExtractor()._table_observations(table)
    products = [item for item in observations if item.metric_original == "Products"]
    assert len(products) == 3
    assert {item.period for item in products} == {"2023", "2024", "2025"}
    assert {item.value for item in products} == {307_003_000_000, 294_866_000_000, 298_085_000_000}
    assert all(item.metric_original not in {"$", "column_1"} for item in observations)


def test_multi_column_financial_table_uses_column_metrics_and_row_dimension() -> None:
    raw = [["Money market funds", "5,272", "177", "(2)", "6,126"]]
    table = ExtractedTable(
        table_id="securities",
        page=40,
        headers=["label", "Adjusted Cost", "Unrealized Gains", "Unrealized Losses", "Fair Value"],
        column_periods=[None, "2025", "2025", "2025", "2025"],
        rows=[TableRow(cells=row, page=40) for row in raw],
        raw_cells=raw,
        confidence=0.9,
    )
    observations = ObservationExtractor()._table_observations(table)
    assert {item.metric_original for item in observations} == {"Adjusted Cost", "Unrealized Gains", "Unrealized Losses", "Fair Value"}
    assert all(item.dimensions == {"category": "Money market funds"} for item in observations)
    assert all(item.period == "2025" for item in observations)
