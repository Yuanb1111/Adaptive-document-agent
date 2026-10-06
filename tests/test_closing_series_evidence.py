"""Conclusions visibly retain intermediate evidence and reported precision."""

import pytest

from adaptive_document_agent.models import (
    DocumentProfile, Observation, ParsedDocument, PipelineResult,
    PresentationSlide, SourceEvidence,
)
from adaptive_document_agent.services.closing_evidence import closing_evidence
from adaptive_document_agent.services.presentation_closing import render_closing
from tests.test_presentation_brief import blank_deck


def _fixture(values=(123456, 198765, 167890, 158432), *, monetary=True):
    items = []
    for index, amount in enumerate(values):
        period = f"{2020 + index}-12-31"
        raw = f"{amount:,}" if monetary else f"{amount:.3f}"
        items.append(Observation(
            id=f"resource-{index}", metric_original="Available resources",
            value=amount * 1000 if monetary else amount, raw_value=raw,
            currency="USD" if monetary else None,
            unit="currency" if monetary else "count",
            raw_unit="USD in thousands" if monetary else "units",
            unit_scale=1000 if monetary else 1,
            period=period, period_basis="point_in_time", period_type="point_in_time",
            as_of_date=period, validation_status="valid", confidence=.99,
            evidence=[SourceEvidence(page=index + 1, text=f"Reported available resources: {raw}",
                                     row_label="Available resources", extraction_method="digital_table",
                                     confidence=.99)],
        ))
    result = PipelineResult(
        document=ParsedDocument(document_id="resources", sha256="synthetic",
                                safe_filename="resources.pdf", page_count=len(items)),
        profile=DocumentProfile(), observations=items,
    )
    ids = [item.id for item in items]
    plan = PresentationSlide(
        id="closing", slide_type="risks", title="Conclusions",
        bullets=["The reported resources increased to their intermediate peak before declining."],
        observation_ids=ids, bullet_observation_ids=[ids], source_pages=list(range(1, len(items) + 1)),
    )
    return result, plan


def _tables(slides):
    return [shape for slide in slides for shape in slide.shapes if shape.has_table]


def test_closing_table_keeps_intermediate_peak_and_exact_monetary_precision():
    result, plan = _fixture()
    before, original_plan = result.model_dump(), plan.model_dump()
    deck = blank_deck()

    slides = render_closing(deck, result, plan)

    assert len(slides) == 1
    table = _tables(slides)[0]
    assert [cell.text for cell in table.table.rows[0].cells] == [
        "Reported values (US$ million)", "31 Dec 2020", "31 Dec 2021", "31 Dec 2022", "31 Dec 2023",
    ]
    assert [cell.text for cell in table.table.rows[1].cells] == [
        "Available resources", "123.456", "198.765", "167.89", "158.432",
    ]
    # A multi-period table needs the full content width, not a narrow sidebar.
    assert table.width.inches > deck.slide_width.inches * .8
    body = next(shape for shape in slides[0].shapes if shape.name == "closing:body")
    assert body.text == plan.bullets[0]
    assert body.top >= table.top + table.height
    assert body.top.inches + body.height.inches < deck.slide_height.inches - 1.0
    notes = slides[0].notes_slide.notes_text_frame.text
    assert all(item.id in notes and item.raw_value in notes for item in result.observations)
    assert result.model_dump() == before and plan.model_dump() == original_plan


def test_nonmonetary_intermediate_observation_keeps_its_exact_raw_precision():
    result, plan = _fixture((12.5, 19.25, 15.75), monetary=False)
    tables, records = closing_evidence(result, plan)

    assert len(tables) == 1
    assert tables[0][1][0][1] == ["12.500", "19.250", "15.750"]
    assert len(tables[0][0][0]) == 3
    assert records == result.observations


def test_long_selected_series_continues_all_periods_without_sampling_or_alignment():
    result, plan = _fixture(tuple(range(12, 24)), monetary=False)
    tables, _ = closing_evidence(result, plan)

    assert [len(key[0]) for key, _ in tables] == [5, 5, 2]
    visible_values = [value for _, rows in tables for _, values, _ in rows for value in values]
    assert visible_values == [item.raw_value for item in result.observations]
    assert len({period for key, _ in tables for period in key[0]}) == 12
    deck = blank_deck()
    slides = render_closing(deck, result, plan)
    cells = [cell.text for shape in _tables(slides) for row in shape.table.rows for cell in row.cells]
    assert all(item.raw_value in cells for item in result.observations)
    assert len(slides) == len(deck.slides)


@pytest.mark.parametrize(("raw_unit", "raw_value", "value", "scale"), [
    ("USD in thousands", "123,456", 123456000, 1000),
    ("USD in thousands", "123,456", 123456, 1),
    ("USD million", "123.456", 123.456, 1),
    ("USD billion", "0.123456", .123456, 1),
])
def test_exact_currency_display_respects_explicit_source_scale(raw_unit, raw_value, value, scale):
    result, plan = _fixture()
    result.observations = [result.observations[0].model_copy(update={
        "raw_unit": raw_unit, "raw_value": raw_value, "value": value, "unit_scale": scale,
    })]
    plan.observation_ids = [result.observations[0].id]
    tables, _ = closing_evidence(result, plan)

    assert tables[0][0][1] == "US$ million"
    assert tables[0][1][0][1] == ["123.456"]


@pytest.mark.parametrize(("raw", "value", "expected"), [
    ("0.29", .29 * 1000, "0.00029"),
    ("0.29 thousand", .29 * 1000, "0.00029"),
    ("(0.29)", -.29 * 1000, "-0.00029"),
    ("1 230.29", 1230.29 * 1000, "1.23029"),
    ("0.29", .31 * 1000, "0.00031"),
])
def test_source_decimal_removes_only_float_residue_and_preserves_real_disagreements(raw, value, expected):
    result, plan = _fixture()
    result.observations = [result.observations[0].model_copy(update={
        "raw_value": raw, "value": value, "unit_scale": 1000,
    })]
    plan.observation_ids = [result.observations[0].id]
    original = result.model_dump()

    tables, _ = closing_evidence(result, plan)

    assert tables[0][1][0][1] == [expected]
    assert result.model_dump() == original
