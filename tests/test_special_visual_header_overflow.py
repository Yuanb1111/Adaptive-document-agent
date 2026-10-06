"""Special visuals keep long analytical copy and its evidence on readable pages."""

import json

import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.services.pptx_export import _source_footer
from adaptive_document_agent.services.presentation_horizon import render_horizon
from adaptive_document_agent.services.presentation_matrix import render_matrix
from adaptive_document_agent.services.presentation_waterfall import render_waterfall
from adaptive_document_agent.services.slide_compositor import validate_composed_geometry
from tests.test_matrix_capacity_regressions import _matrix
from tests.test_presentation_brief import blank_deck
from tests.test_presentation_horizon import _example
from tests.test_presentation_waterfall import _bridge


KINDS = ("matrix", "waterfall", "horizon")
SHORT = "The reported source values retain their original scope."
SINGLE_SENTENCE = (
    "The selected reported values retain their complete original measurement context "
    "together with the source terminology and the distinct reporting periods so that "
    "readers can compare the evidence without overlooking qualifiers about coverage "
    "or treating differently scoped observations as interchangeable measurements."
)
MULTIPLE_SENTENCES = SHORT + " " + SINGLE_SENTENCE
MANY_SENTENCES = " ".join(
    f"Evidencepart{i:03d} retains the original measurement context and its cited source "
    "so that the reader can review the complete reporting scope and qualifications."
    for i in range(55)
)


def _fixture(kind):
    document = None
    if kind == "matrix":
        items, block, plan = _matrix(row_count=2)
        index = {item.id: item for item in items}
        plan = plan.model_copy(update={"title": "Category comparison", "section_title": "Categories"})
    elif kind == "waterfall":
        items, block = _bridge()
        index = {item.id: item for item in items}
        plan = PresentationSlide(
            id="bridge", slide_type="analysis", title="Reported reconciliation",
            section_title="Components", visual_blocks=[block], source_pages=[4],
        )
    else:
        document, index, block = _example()
        plan = PresentationSlide(
            id="horizon", slide_type="analysis", title="Resource timing",
            section_title="Timing", visual_blocks=[block], source_pages=[1],
        )
    return plan.model_copy(update={"message": SHORT}), block, index, document


def _render(kind, deck, plan, block, index, document):
    if kind == "matrix":
        return render_matrix(deck, plan, block, index)
    if kind == "waterfall":
        return render_waterfall(deck, plan, block, index)
    return render_horizon(deck, plan, block, index, document)


def _visible(slide):
    return [shape.text for shape in slide.shapes if shape.has_text_frame and shape.text.strip()]


def _retained_message(deck, message):
    # Header and body may split at different sentence boundaries. Collect the
    # exact source fragments, excluding repeated headings and source footers.
    pieces = [text.strip() for slide in deck.slides for text in _visible(slide)
              if text.strip() in message]
    return " ".join(" ".join(pieces).split())


def _visual_data(deck):
    tables, charts, horizon = [], [], []
    for slide in deck.slides:
        for shape in slide.shapes:
            if shape.has_table:
                tables.append([[cell.text for cell in row.cells] for row in shape.table.rows])
            if shape.has_chart:
                charts.append([list(series.values) for series in shape.chart.series])
            if shape.name.startswith("horizon:"):
                horizon.append((shape.name, shape.text))
    return tables, charts, horizon


def _nested_dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _nested_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_dicts(item)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("message", (SINGLE_SENTENCE, MULTIPLE_SENTENCES, MANY_SENTENCES),
                         ids=("single-sentence", "several-sentences", "many-pages"))
def test_special_visual_overflow_retains_message_data_and_evidence(kind, message):
    plan, block, index, document = _fixture(kind)
    reference = blank_deck()
    _render(kind, reference, plan, block, index, document)
    expected_data = _visual_data(reference)

    plan = plan.model_copy(update={"message": message})
    original_plan = plan.model_dump(mode="json")
    original_items = [item.model_dump(mode="json") for item in index.values()]
    deck = blank_deck()
    first = _render(kind, deck, plan, block, index, document)

    assert first == deck.slides[0]
    assert len(deck.slides) > 1
    if message == MANY_SENTENCES:
        assert len(deck.slides) > 2
    assert _retained_message(deck, message) == " ".join(message.split())
    assert _visual_data(deck) == expected_data
    validate_composed_geometry(deck)
    assert plan.model_dump(mode="json") == original_plan
    assert [item.model_dump(mode="json") for item in index.values()] == original_items

    pages = sorted({source.page for item in index.values() for source in item.evidence})
    for continuation in list(deck.slides)[1:]:
        assert _source_footer(pages) in "\n".join(_visible(continuation))
        notes = json.loads(continuation.notes_slide.notes_text_frame.text)
        assert message in [value for record in _nested_dicts(notes) for value in record.values()
                           if isinstance(value, str)]
        retained = list(_nested_dicts(notes))
        for item in original_items:
            assert item in retained
        if kind == "horizon":
            assert block.horizon_items[-1].model_dump(mode="json") in retained


@pytest.mark.parametrize("kind", KINDS)
def test_short_special_visual_header_stays_on_one_page(kind):
    plan, block, index, document = _fixture(kind)
    deck = blank_deck()
    first = _render(kind, deck, plan, block, index, document)

    assert first == deck.slides[0]
    assert len(deck.slides) == 1
    assert SHORT in _visible(first)


@pytest.mark.parametrize("kind", KINDS)
def test_long_special_visual_title_stays_visible_with_original_message(kind):
    plan, block, index, document = _fixture(kind)
    title = SINGLE_SENTENCE
    plan = plan.model_copy(update={"title": title})
    original = plan.model_dump(mode="json")
    deck = blank_deck()
    _render(kind, deck, plan, block, index, document)

    visible = " ".join(" ".join(_visible(slide)) for slide in deck.slides)
    assert title in visible
    assert SHORT in visible
    assert plan.model_dump(mode="json") == original


@pytest.mark.parametrize("kind", KINDS)
def test_overflow_does_not_hide_invalid_special_visual_evidence(kind):
    plan, block, index, document = _fixture(kind)
    plan = plan.model_copy(update={"message": MANY_SENTENCES})
    next(iter(index.values())).evidence = []
    deck = blank_deck()

    with pytest.raises(ValueError, match={
        "matrix": "valid reported values",
        "waterfall": "valid source observations",
        "horizon": "valid, selected and cited",
    }[kind]):
        _render(kind, deck, plan, block, index, document)
    assert len(deck.slides) == 0
