"""Supplemental interim evidence cannot duplicate identical annual rows."""

import copy

from adaptive_document_agent.services.appendix_source_deduplication import deduplicate_period_entries


def _themes():
    def entry(label, page, values):
        return {"label": label, "unit": "%", "pages": {page}, "records": [f"record-{page}"],
                "values": values, "periods": {p: f"{v}%" for p, v in values.items()},
                "raw_signatures": {p: {(f"{v}%", "%", "percent", 1, None, p, "FY")} for p, v in values.items()}}
    return {"Capacity": {
        ("Utilisation", "source1", "percent", None, "site", "FY", "reported"):
            entry("Utilisation [source 1]", 10, {"FY2022": 35, "FY2023": 45, "6M2024": 40}),
        ("Utilisation", "source2", "percent", None, "site", "FY", "reported"):
            entry("Utilisation [source 2]", 20, {"FY2022": 35, "FY2023": 45}),
    }}


def test_exact_annual_rows_merge_without_losing_records_or_changing_inputs():
    themes = _themes()
    before = copy.deepcopy(themes)
    output = deduplicate_period_entries(themes, ("FY2022", "FY2023"))["Capacity"]
    assert len(output) == 1
    entry = next(iter(output.values()))
    assert entry["label"] == "Utilisation"
    assert entry["pages"] == {10, 20}
    assert entry["records"] == ["record-10", "record-20"]
    assert themes == before


def test_conflicting_numeric_or_raw_values_or_units_remain_separate():
    for change in ("value", "raw", "unit", "partial"):
        themes = _themes()
        second = list(themes["Capacity"].values())[1]
        if change == "value":
            second["values"]["FY2023"] = 46
        elif change == "raw":
            second["raw_signatures"]["FY2023"] = {("45.0%", "%")}
        elif change == "unit":
            second["unit"] = "days"
        else:
            second["values"].pop("FY2022")
        assert len(deduplicate_period_entries(themes, ("FY2022", "FY2023"))["Capacity"]) == 2
