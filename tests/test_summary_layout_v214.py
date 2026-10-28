"""Localized spelling must not erase structure or disagree with native pagination."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from adaptive_document_agent.models.summary import SummarySlideItem, SummarySlidePage
from adaptive_document_agent.models.summary_display import SummaryDisplay
from adaptive_document_agent.services.summary_display_copy import summary_display
from adaptive_document_agent.services.summary_visual_layout import summary_brief_items, display_segments
from adaptive_document_agent.services.presentation_brief import render_profile
from adaptive_document_agent.services.compact_summary import compact_layout_errors
from adaptive_document_agent.agent.summary_theme_layout import pack_theme_pages
from tests.test_presentation_brief import blank_deck


SOURCE = ('The market reached US$120.5 million in 2023. '
          'Revenue was RMB24.0 million in 2023. The outlook remains uncertain.')
LOCALIZED = SOURCE.replace('US$', 'USD ').replace('RMB24.0', 'RMB 24.0')


def item(text=SOURCE, layout='key_metrics'):
    return SummarySlideItem(label='Reported measures', text=text, source_quote=text,
        source_pages=[1], part_ids=['source-part'],
        display=SummaryDisplay(layout=layout, break_after=['Revenue was RMB24.0 million in 2023.']))


def test_currency_spacing_maps_exact_anchors_without_changing_reviewed_copy_or_bindings():
    original = item()
    before = original.model_dump_json()
    display = summary_display(original, LOCALIZED)
    assert display.layout == 'key_metrics'
    assert display.break_after == ['Revenue was RMB 24.0 million in 2023.']
    assert ''.join(display_segments(LOCALIZED, display)) == LOCALIZED
    assert original.model_dump_json() == before


@pytest.mark.parametrize('changed', [
    LOCALIZED.replace('USD', 'HKD'), LOCALIZED.replace('120.5', '120.6'),
    LOCALIZED.replace('120.5', '-120.5'), LOCALIZED.replace('million', 'billion'),
    LOCALIZED.replace('2023', '2024'), LOCALIZED.replace('uncertain', 'certain'),
    'The outlook remains uncertain. Revenue was RMB 24.0 million in 2023.',
    '市场达到美元120.5百万元，收入为人民币24.0百万元。',
])
def test_rewording_and_changed_quantities_cannot_borrow_authored_semantic_structure(changed):
    display = summary_display(item(), changed)
    assert display == SummaryDisplay()


def test_unmappable_anchor_is_dropped_without_erasing_proven_structure():
    original = item()
    original.display.break_after = ['not present']
    assert summary_display(original, LOCALIZED) == SummaryDisplay(layout='key_metrics')


def test_native_soft_line_breaks_preserve_authored_newlines_in_capacity_probe():
    from adaptive_document_agent.services.summary_native_capacity import native_summary_capacity
    source = '\n'.join(['Supported service.'] * 6)
    page = SummarySlidePage(id='p', title='Service scope', source_section='Source', items=[item(source, 'paragraphs')])
    assert native_summary_capacity(page) == (1, True)
    assert not compact_layout_errors([page])
    assert page.items[0].text == source


def test_export_item_preparation_uses_checked_spelling_and_keeps_original_evidence():
    page = SummarySlidePage(id='p', title='Source measures', source_section='Source', items=[item()], compact=True)
    before = page.model_dump_json()
    result = SimpleNamespace(profile=SimpleNamespace(report_requirements=SimpleNamespace(
        summary_copy_translations={'p:0': LOCALIZED}, copy_translations={})))
    rows = summary_brief_items(result, page)
    assert rows[0].text == LOCALIZED and rows[0].display.layout == 'key_metrics'
    deck = blank_deck()
    slides = render_profile(deck, page.title, rows)
    assert len(slides) == 1
    assert ''.join(s.text for slide in slides for s in slide.shapes if s.name == 'brief:body') == LOCALIZED
    assert page.model_dump_json() == before


@pytest.mark.parametrize('layout', ['paragraphs', 'key_metrics', 'timeline'])
def test_packed_source_groups_really_render_one_slide_without_lost_copy(layout):
    text = 'Teams provide installation and training under the stated operating conditions. ' * 6
    values = [item(text + f'Team {letter} retains those conditions.', layout) for letter in 'ABC']
    page = SummarySlidePage(id='p', title='Delivery and operating conditions', source_section='Source',
        items=values, compact=True)
    before = page.model_dump_json()
    packed = pack_theme_pages([page])
    result = SimpleNamespace(profile=SimpleNamespace(report_requirements=None))
    deck = blank_deck()
    for candidate in packed:
        assert not compact_layout_errors([candidate])
        slides = render_profile(deck, candidate.title, summary_brief_items(result, candidate))
        assert len(slides) == 1
    assert ''.join(s.text for slide in deck.slides for s in slide.shapes if s.name == 'brief:body') == ''.join(i.text for i in values)
    assert page.model_dump_json() == before
