"""Shared prose keeps independent display coverage outside bound introduction parts."""
from pptx import Presentation
from pptx.util import Inches

from adaptive_document_agent.services.report_language import audience_copy


def test_introduction_part_exclusion_is_by_shape_role_not_identical_text():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    duplicated = 'The estimate remains conditional on testing and market needs.'
    unique = 'A separately bound introduction detail.'
    for index, (text, introduction) in enumerate([(duplicated, True), (unique, True), (duplicated, False)]):
        shape = slide.shapes.add_textbox(Inches(1), Inches(index + 1), Inches(7), Inches(.6))
        shape.text = text
        if introduction:
            shape.element.xpath('.//p:cNvPr')[0].set('descr', 'ADA_SUMMARY_ITEM_V2:{}')
    assert audience_copy(deck) == [duplicated, unique]
    assert audience_copy(deck, exclude_summary_items=True) == [duplicated]
