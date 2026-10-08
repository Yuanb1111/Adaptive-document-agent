"""Complete agendas use available space without shrinking or dropping sections."""

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.services.pptx_export import _add_planned_contents
from adaptive_document_agent.services.text_capacity import wrap_copy
from tests.test_presentation_brief import blank_deck


def _entries(deck):
    return [shape for slide in deck.slides for shape in slide.shapes
            if shape.name.startswith("contents:entry:")]


def test_fifteen_authored_sections_fit_one_readable_page_without_cards():
    labels = [
        "Company overview", "Product portfolio", "Executive summary", "Key figures",
        "Service demand", "Installed equipment",
        "Annual research and development investment",
        "Regional service capacity and staffing requirements",
        "Channel mix", "New subscriptions", "Customer retention",
        "Operating expenditure", "Conclusions", "Coverage and limits", "Data index",
    ]
    plans = [PresentationSlide(
        id=f"section-{i}", slide_type="analysis", section_title=label,
        title=f"The complete analytical finding for section {i} remains on its analysis page",
    ) for i, label in enumerate(labels)]
    original = [item.model_dump() for item in plans]
    deck = blank_deck()

    _add_planned_contents(deck, plans)

    assert len(deck.slides) == 1
    entries = _entries(deck)
    assert [shape.text for shape in entries] == labels
    assert len({shape.left for shape in entries}) == 2
    assert all(shape.text_frame.paragraphs[0].font.size.pt >= 16 for shape in entries)
    for shape in entries:
        paragraph = shape.text_frame.paragraphs[0]
        needed = len(wrap_copy(shape.text, shape.width.inches, paragraph.font.size.pt))
        needed = needed * paragraph.line_spacing.pt / 72
        margins = shape.text_frame.margin_top.inches + shape.text_frame.margin_bottom.inches
        assert needed + margins <= shape.height.inches + 1e-6
        assert shape.top.inches + shape.height.inches <= deck.slide_height.inches - 1.0
    assert [item.model_dump() for item in plans] == original


def test_unnamed_analysis_sections_keep_their_distinct_authored_titles():
    labels = ["Staffing requirements", "Service reliability", "Demand outlook"]
    plans = [PresentationSlide(id=str(i), slide_type="analysis", title=label,
                               section_title=" " if i == 1 else "")
             for i, label in enumerate(labels)]
    deck = blank_deck()

    _add_planned_contents(deck, plans)

    assert [shape.text for shape in _entries(deck)] == labels


def test_shared_authored_section_is_listed_once_without_losing_other_sections():
    plans = [
        PresentationSlide(id="a", slide_type="analysis", title="First finding",
                          section_title="Operational performance"),
        PresentationSlide(id="b", slide_type="analysis", title="Second finding",
                          section_title="Operational performance"),
        PresentationSlide(id="c", slide_type="analysis", title="Third finding",
                          section_title="Service risks"),
    ]
    deck = blank_deck()

    _add_planned_contents(deck, plans)

    assert [shape.text for shape in _entries(deck)] == ["Operational performance", "Service risks"]


def test_large_agenda_remains_one_page_and_every_section_is_recoverable():
    labels = [f"Section {i}: " + ("qualified operational evidence " * 6).rstrip() for i in range(45)]
    deck = blank_deck()
    _add_planned_contents(deck, [PresentationSlide(id=str(i), slide_type="analysis", title=label)
                                for i, label in enumerate(labels)])
    assert len(deck.slides) == 1
    entries = _entries(deck)
    assert len(entries) == 30
    assert "16 further sections" in entries[-1].text
    notes = deck.slides[0].notes_slide.notes_text_frame.text
    assert all(label in notes for label in labels)
    assert all(shape.top.inches + shape.height.inches <= deck.slide_height.inches - 1 + .001
               for shape in entries)
