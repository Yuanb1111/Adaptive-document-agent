"""Oversized conclusion groups keep complete shared evidence in balanced pages."""

from copy import deepcopy

import pytest

from adaptive_document_agent.models import Insight, PresentationSlide
from adaptive_document_agent.services.closing_evidence import closing_evidence
from adaptive_document_agent.services.presentation_closing import render_closing
from tests.test_closing_series_evidence import _fixture
from tests.test_presentation_brief import blank_deck


@pytest.mark.parametrize(("copy", "page_count"), [
    ("The reported series retains each original source period and measurement context. "
     "The evidence supports this finding with its source qualifications.", 2),
    ("The selected reported series retains its complete measurement context and each original source period. "
     "These observations support the stated finding while keeping its source qualifications visible to the reader.", 2),
])
def test_linked_findings_pack_only_when_complete_evidence_and_copy_fit(copy, page_count):
    result, _ = _fixture((123456, 145678, 167890))
    base = result.observations
    result.observations = []
    groups = []
    for number, metric in enumerate(("Measure Alpha", "Measure Beta", "Measure Gamma", "Measure Delta", "Measure Epsilon")):
        group = [item.model_copy(deep=True, update={"id": f"measure-{number}-{index}",
                 "metric_original": metric, "value": item.value + number * 1000,
                 "raw_value": str(item.value / 1000 + number)}) for index, item in enumerate(base)]
        for item in group:
            item.evidence[0].row_label = metric
        result.observations.extend(group)
        groups.append([item.id for item in group])
    scopes = [groups[0], groups[3], sum(groups[:4], []), groups[4]]
    texts = [f"Finding {number + 1}: {copy}" for number in range(4)]
    result.insights = [Insight(id=f"insight-{number}", title=f"Supported finding {number+1}",
        narrative=text, metric=f"Topic {number+1}", kind="interpretation", importance=.9, confidence=.99,
        evidence=[base[0].evidence[0]]) for number, text in enumerate(texts)]
    plan = PresentationSlide(id="closing", slide_type="risks", title="Conclusions",
        bullets=texts, bullet_observation_ids=scopes, observation_ids=sum(groups, []),
        insight_ids=[insight.id for insight in result.insights], source_pages=[1, 2, 3])
    before = deepcopy(result.model_dump()), deepcopy(plan.model_dump())
    expected, _ = closing_evidence(result, plan)
    deck = blank_deck()

    slides = render_closing(deck, result, plan)

    assert len(slides) == page_count
    visible_bodies = [shape.text for slide in slides for shape in slide.shapes if shape.name == "closing:body"]
    assert visible_bodies == texts
    tables = [shape for slide in slides for shape in slide.shapes if shape.has_table]
    cells = [cell.text for shape in tables for row in shape.table.rows for cell in row.cells]
    assert all(label in cells and all(value in cells for value in values)
               for _, rows in expected for label, values, _ in rows)
    for slide in slides:
        body = [shape for shape in slide.shapes if shape.name == "closing:body"]
        if page_count == 2:
            assert len(body) == 2
        assert all(shape.top.inches + shape.height.inches < deck.slide_height.inches - 1.0 for shape in body)
    assert (result.model_dump(), plan.model_dump()) == before


@pytest.mark.parametrize(("unit", "raw_unit", "currency"), [
    ("count", "units", None),
    ("percent", "%", None),
    ("currency", "USD/unit", "USD"),
])
def test_matching_periods_balance_findings_across_distinct_unit_tables(unit, raw_unit, currency):
    result, _ = _fixture((123456, 145678, 167890))
    base = result.observations
    result.observations = []
    groups = []
    for number, metric in enumerate(("Measure Alpha", "Measure Beta", "Measure Gamma", "Measure Delta")):
        group = []
        for index, item in enumerate(base):
            updates = {"id": f"measure-{number}-{index}", "metric_original": metric,
                       "period": f"FY{2020 + index}", "period_basis": "FY",
                       "period_type": "fiscal_year", "as_of_date": None}
            if number == 2:
                updates.update(unit=unit, raw_unit=raw_unit, currency=currency,
                               unit_scale=1, value=12.5 + index, raw_value=f"{12.5 + index:.2f}")
            observation = item.model_copy(deep=True, update=updates)
            observation.evidence[0].row_label = metric
            group.append(observation)
        result.observations.extend(group)
        groups.append([item.id for item in group])
    copy = ("The reported series retains each original source period and measurement context. "
            "The evidence supports this finding with its source qualifications.")
    texts = [f"Finding {number + 1}: {copy}" for number in range(4)]
    plan = PresentationSlide(id="closing", slide_type="risks", title="Conclusions",
        bullets=texts, bullet_observation_ids=groups, observation_ids=sum(groups, []), source_pages=[1, 2, 3])
    before = deepcopy(result.model_dump()), deepcopy(plan.model_dump())
    expected, _ = closing_evidence(result, plan)
    deck = blank_deck()

    slides = render_closing(deck, result, plan)

    assert len(slides) == len(deck.slides) == 2
    assert [[shape.text for shape in slide.shapes if shape.name == "closing:body"] for slide in slides] == [texts[:2], texts[2:]]
    assert len([shape for shape in slides[1].shapes if shape.has_table]) == 2
    # Each distinct unit retains its own full period header and every value.
    actual = [shape.table for slide in slides for shape in slide.shapes if shape.has_table]
    for (periods, display_unit), rows in expected:
        matching = [table for table in actual if table.cell(0, 0).text == f"Reported values ({display_unit})"]
        assert matching
        assert all([cell.text for cell in table.rows[0].cells][1:] == list(periods) for table in matching)
        visible_rows = [[cell.text for cell in row.cells] for table in matching for row in list(table.rows)[1:]]
        assert all([label, *values] in visible_rows for label, values, _ in rows)
    for slide in slides:
        for shape in slide.shapes:
            if shape.has_table or shape.name == "closing:body":
                assert shape.top.inches + shape.height.inches < deck.slide_height.inches - 1.0
        assert all(item.id in slide.notes_slide.notes_text_frame.text for item in result.observations)
    assert (result.model_dump(), plan.model_dump()) == before
