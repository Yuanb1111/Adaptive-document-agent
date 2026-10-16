"""One author's complete thematic group is paginated by real template capacity."""
import pytest

from adaptive_document_agent.agent.compact_summary import (
    CompactSummaryDraft, compact_input, expand_compact)
from adaptive_document_agent.agent.summary_theme_layout import (
    SummaryLayoutError, pack_theme_items, pack_theme_pages)
from adaptive_document_agent.models.summary import SummarySlidePage
from adaptive_document_agent.services.compact_summary import compact_layout_errors
from tests.test_compact_summary_v111 import fixture


def authored_items(count):
    return [dict(label='Service condition', text=('Supported service words ' * 12 + f'Team {chr(65 + index)}.').strip(),
                 fact_ids=[f'f{index}']) for index in range(count)]


def prepared_group(count=6):
    _, review, _ = fixture(count)
    _, catalog = compact_input(review)
    draft = CompactSummaryDraft(pages=[dict(title='Service delivery', items=authored_items(count))])
    return review, catalog, draft


def test_complete_group_avoids_staging_boundaries_without_losing_copy_or_evidence():
    review, catalog, draft = prepared_group()
    pages = expand_compact(draft, catalog, review)
    assert len(pages) == 2
    assert [len(page.items) for page in pages] == [3, 3]
    assert not compact_layout_errors(pages)
    assert [item.text for page in pages for item in page.items] == [i.text for i in draft.pages[0].items]
    assert [item.source_refs[0].part_id for page in pages for item in page.items] == [f'part-{i}' for i in range(6)]
    # Every continuation title keeps the complete original group's source
    # union, while each paragraph retains only its actual owned source.
    assert all(len(page.title_source_refs) == 6 for page in pages)
    assert all(len(item.source_refs) == 1 for page in pages for item in page.items)
    assert all(SummarySlidePage.model_validate(page.model_dump()) == page for page in pages)
    assert [p.model_dump(exclude={'id'}) for p in pack_theme_pages(pages)] == [
        p.model_dump(exclude={'id'}) for p in pages]


@pytest.mark.parametrize('second_title', ['Service delivery', 'Customer training'])
def test_distinct_authored_groups_remain_separate_even_when_their_titles_match(second_title):
    review, catalog, _ = prepared_group(4)
    items = authored_items(4)
    draft = CompactSummaryDraft(pages=[
        dict(title='Service delivery', items=items[:2]), dict(title=second_title, items=items[2:])])
    pages = pack_theme_pages(expand_compact(draft, catalog, review))
    assert len(pages) == 2
    assert [page.title for page in pages] == ['Service delivery', second_title]
    assert [[item.source_refs[0].part_id for item in page.items] for page in pages] == [
        ['part-0', 'part-1'], ['part-2', 'part-3']]


def test_grid_candidates_are_considered_after_a_vertical_candidate_fails(monkeypatch):
    """The fit contract supports a grid; prefix failure is not an end marker."""
    review, catalog, draft = prepared_group(3)
    prototype = expand_compact(draft, catalog, review)[0]
    from adaptive_document_agent.agent import summary_theme_layout
    seen = []
    def grid_geometry(pages):
        size = len(pages[0].items)
        seen.append(size)
        return ['Vertical rows exceed body capacity'] if size == 2 else []
    monkeypatch.setattr(summary_theme_layout, 'compact_layout_errors', grid_geometry)
    assert len(pack_theme_items(prototype, prototype.items)) == 1
    assert 2 in seen and 3 in seen


def test_pagination_search_is_bounded_by_four_candidate_sizes_per_item(monkeypatch):
    review, catalog, draft = prepared_group(25)
    pages = expand_compact(draft, catalog, review)
    items = [item for page in pages for item in page.items]
    from adaptive_document_agent.agent import summary_theme_layout
    checks = []
    original = summary_theme_layout.compact_layout_errors
    def counted(candidate):
        checks.append(len(candidate[0].items))
        return original(candidate)
    monkeypatch.setattr(summary_theme_layout, 'compact_layout_errors', counted)
    packed = pack_theme_items(pages[0], items)
    assert len(checks) <= len(items) * 5
    assert max(checks) <= 4
    assert [i.model_dump() for page in packed for i in page.items] == [i.model_dump() for i in items]


def test_impossible_whole_paragraph_fails_instead_of_changing_its_copy():
    review, catalog, draft = prepared_group(1)
    page = expand_compact(draft, catalog, review)[0]
    item = page.items[0].model_copy(update={'text': '交付前须完成客户集成和员工培训。' * 60})
    original = item.model_dump()
    assert compact_layout_errors([page.model_copy(update={'items': [item]})])
    with pytest.raises(SummaryLayoutError, match='shorter complete model-authored copy'):
        pack_theme_items(page, [item])
    assert item.model_dump() == original


def test_overflowing_title_is_not_repaired_by_splitting_or_rewriting_body(monkeypatch):
    from adaptive_document_agent.agent import summary_editorial
    from adaptive_document_agent.agent.summary_theme_layout import split_compact_item
    review, catalog, draft = prepared_group(1)
    item = expand_compact(draft, catalog, review)[0].items[0]
    original = item.model_dump()
    def must_not_split(*args, **kwargs):
        raise AssertionError('Title overflow must not spend a body continuation attempt')
    monkeypatch.setattr(summary_editorial, 'split_editorial_copy', must_not_split)
    with pytest.raises(SummaryLayoutError, match='title'):
        split_compact_item(item.text, ('WWWW ' * 13).strip(), 'title-overflow',
            item.model_dump(exclude={'text'}))
    assert item.model_dump() == original


def test_whole_group_title_overflow_has_a_distinct_failure_from_body_overflow():
    review, catalog, draft = prepared_group(1)
    page = expand_compact(draft, catalog, review)[0]
    overflow = page.model_copy(update={'title': ('WWWW ' * 13).strip()})
    original = overflow.model_dump()
    with pytest.raises(SummaryLayoutError, match='title'):
        pack_theme_items(overflow, overflow.items)
    assert overflow.model_dump() == original


def test_native_three_line_title_remains_allowed_when_its_body_fits():
    review, catalog, draft = prepared_group(1)
    draft.pages[0].title = ('WWWW ' * 9).strip()
    draft.pages[0].items[0].text = 'Staff training is required before service delivery.'
    pages = expand_compact(draft, catalog, review)
    assert len(pages) == 1 and not compact_layout_errors(pages)
    assert pages[0].items[0].text == draft.pages[0].items[0].text


def test_wrapped_continuation_title_reservation_cannot_add_unplanned_native_slides():
    from pptx import Presentation
    from adaptive_document_agent.services.pptx_export import BUNDLED_TEMPLATE_PATH
    from adaptive_document_agent.services.presentation_brief import BriefItem, render_profile
    review, catalog, draft = prepared_group(1)
    draft.pages[0].title = ('WWWW ' * 12).strip()
    original = '交付前须完成客户集成和员工培训。' * 29
    draft.pages[0].items[0].text = original
    pages = expand_compact(draft, catalog, review)
    assert ''.join(item.text for page in pages for item in page.items) == original
    deck = Presentation(str(BUNDLED_TEMPLATE_PATH))
    for page in pages:
        actual = render_profile(deck, page.title, [BriefItem(item.label, item.text, item.source_pages)
                                                 for item in page.items])
        assert len(actual) == 1


def test_overflowing_paragraph_heading_does_not_split_its_supported_body(monkeypatch):
    from adaptive_document_agent.agent import summary_editorial
    from adaptive_document_agent.agent.summary_theme_layout import split_compact_item
    review, catalog, draft = prepared_group(1)
    item = expand_compact(draft, catalog, review)[0].items[0]
    def must_not_split(*args, **kwargs):
        raise AssertionError('Heading overflow cannot be fixed by splitting paragraph text')
    monkeypatch.setattr(summary_editorial, 'split_editorial_copy', must_not_split)
    values = item.model_dump(exclude={'text'})
    values['label'] = 'Service\nCustomer\nAcceptance'
    with pytest.raises(SummaryLayoutError, match='paragraph heading'):
        split_compact_item(item.text, 'Service delivery', 'heading-overflow', values)


def test_group_rejects_a_three_line_paragraph_heading_before_pagination():
    review, catalog, draft = prepared_group(1)
    page = expand_compact(draft, catalog, review)[0]
    page.items[0].label = 'Service\nCustomer\nAcceptance'
    with pytest.raises(SummaryLayoutError, match='paragraph heading'):
        pack_theme_items(page, page.items)


def test_native_two_line_paragraph_heading_remains_allowed_with_complete_body():
    review, catalog, draft = prepared_group(1)
    draft.pages[0].items[0].label = 'Service\nDelivery'
    pages = expand_compact(draft, catalog, review)
    assert len(pages) == 1 and not compact_layout_errors(pages)
    assert pages[0].items[0].text == draft.pages[0].items[0].text
