"""Actual template capacity, not 1200 characters, decides continuation layout."""
from copy import deepcopy
from hashlib import sha256

import pytest
from pptx import Presentation

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, compact_input, expand_compact
from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
from adaptive_document_agent.agent.summary_theme_layout import split_compact_item, pack_theme_pages
from adaptive_document_agent.models.summary import SummarySlidePage, SummarySlideItem
from adaptive_document_agent.models.summary_display import SummaryDisplay
from adaptive_document_agent.services.compact_summary import compact_layout_errors
from adaptive_document_agent.services.presentation_brief import BriefItem, render_profile
from adaptive_document_agent.services.pptx_export import _resolve_template_path
from tests.test_compact_summary_v111 import fixture


def expanded(text):
    values = dict(label='Delivery conditions', source_quote=text, source_pages=[1], part_ids=['part'])
    items = split_compact_item(text, 'Service delivery', 'test', values)
    page = SummarySlidePage(id='test', title='Service delivery', source_section='Service delivery',
        compact=True, items=[items[0]])
    from adaptive_document_agent.agent.summary_theme_layout import pack_theme_items
    return items, pack_theme_items(page, items)


@pytest.mark.parametrize('text', ['Teams provide training and support for deployment. ' * 24,
    'Training and installation support remain available. ' * 24])
def test_intact_long_paragraph_has_one_native_page_and_survives_serialization(text):
    assert len(text) > 1200
    items, pages = expanded(text)
    assert len(items) == len(pages) == 1
    assert items[0].text == text and not items[0].continuation_group
    assert SummarySlidePage.model_validate_json(pages[0].model_dump_json()) == pages[0]
    assert not compact_layout_errors(pages)
    deck = Presentation(_resolve_template_path())
    rendered = render_profile(deck, pages[0].title, [BriefItem(items[0].label, text, [1], display=SummaryDisplay())])
    assert len(rendered) == 1
    assert ''.join(shape.text for slide in rendered for shape in slide.shapes if shape.name == 'brief:body') == text


@pytest.mark.parametrize('text', ['Teams provide training and support for deployment. ' * 60,
    'WWW WWW ' * 140])
def test_actual_overflow_still_splits_losslessly_and_keeps_continuation_provenance(text):
    items, pages = expanded(text)
    assert len(items) > 1
    assert ''.join(item.text for item in items) == text
    assert not compact_layout_errors(pages)
    assert [item.continuation_index for item in items] == list(range(len(items)))
    assert all(item.continuation_count == len(items) and
        item.continuation_digest == sha256(text.encode()).hexdigest() for item in items)
    assert len({item.continuation_group for item in items}) == 1


def test_fitting_recorded_style_draft_needs_no_model_rewrite_or_budget_change():
    _, review, _ = fixture(1)
    text = 'Training and installation support remain available. ' * 24
    fact = review.parts[0].facts[0]
    fact.text = fact.source_quote = text
    review.parts[0].source_text = text
    review.max_intro_slides = 1
    _, catalog = compact_input(review)
    draft = CompactSummaryDraft(pages=[dict(title='Service delivery', items=[dict(
        label='Delivery conditions', text=text, fact_ids=list(catalog))])])
    original = deepcopy((review, draft))
    class NoModel:
        def generate_structured(self, *args, **kwargs):
            pytest.fail('Measured fitting copy must not trigger rewriting or layout selection.')
    audit = {}
    final, pages = paginate_draft(NoModel(), draft, catalog, review, [], audit,
        expand_compact, CompactSummaryDraft)
    assert final == draft and len(pages) == 1
    assert draft == original[1]
    assert review.parts == original[0].parts and review.source_blocks == original[0].source_blocks
    assert review.max_intro_slides == original[0].max_intro_slides
    assert review.status == 'incomplete'
    assert [attempt['status'] for attempt in audit['layout_attempts']] == ['success']


def test_storage_bound_does_not_authorize_an_overflowing_single_slide():
    items, _ = expanded('Teams provide training and support for deployment. ' * 60)
    long_item = SummarySlideItem.model_validate({**items[0].model_dump(), 'text': 'WWW WWW ' * 500})
    page = SummarySlidePage(id='bad', title='Service delivery', source_section='Service delivery',
        compact=True, items=[long_item])
    assert compact_layout_errors([page])
    with pytest.raises(ValueError):
        pack_theme_pages([page])
