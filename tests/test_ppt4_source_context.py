"""Generic regressions from PPT4: wrapped parents, date labels and source identity."""

from types import SimpleNamespace

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.services.pptx_export import _chart_category_labels, _presentation_chart_title


def test_wrapped_parent_and_first_child_survive_borderless_extraction():
    page = SimpleNamespace(text="""FINANCIAL INFORMATION
Year ended December 31,
2021 2022 2023
(RMB in thousands)
(unaudited)
Government grants
related to
– Production facilities in
Northport and Southport .... 2,469 15,225 21,752
– Research and development 8,945 15,266 10,331
– Talents ... 104 378 563
Total ... 11,518 30,869 32,646
""")
    tables = BorderlessTableExtractor().extract(page, 42)
    assert len(tables) == 1
    observations = ObservationExtractor()._table_observations(tables[0])
    rd = [o for o in observations if o.metric_original == "Research and development"]
    assert len(rd) == 3
    assert all(o.parent_section == "Government grants related to" for o in rd)
    assert all(display_metric_name(o) == "Government grants related to Research and development" for o in rd)
    assert [o.value for o in rd] == [8_945_000, 15_266_000, 10_331_000]
    assert [o.raw_value for o in rd] == ["8,945", "15,266", "10,331"]
    assert all(o.evidence[0].page == 42 for o in rd)
    assert "Government grants" in _presentation_chart_title("Research and development", rd)
    assert any(o.metric_original == "Production facilities in Northport and Southport" for o in observations)


def test_crowded_snapshot_dates_wrap_without_changing_period_or_audit_marker():
    dates = ["31 Dec 2021", "31 Dec 2022", "31 Dec 2023", "30 Jun 2024*", "31 Oct 2024*"]
    compact = _chart_category_labels(dates, 5.6)
    assert all("\n" in label for label in compact)
    assert [label.replace("\n", " ") for label in compact] == dates
    assert _chart_category_labels(dates, 11.3) == dates
    assert _chart_category_labels(["FY2021", "FY2022", "FY2023"], 5.6) == ["FY2021", "FY2022", "FY2023"]
