import pytest

from adaptive_document_agent.agent.retained_page_revision import _owned_correction_source_pages


@pytest.mark.parametrize('reason,cited_pages', [
    ('Source p. 30: preserve the complete material qualification.', {30}),
    ('Source pp. 30–32: retain each period-specific driver.', {30, 31, 32}),
])
def test_explicit_physical_citations_keep_anchor_and_adjacent_source_pages(reason,cited_pages):
    available_pages=set(range(1,41))
    anchors={10}
    expected=({page for anchor in anchors for page in range(anchor-2,anchor+3)}
              | {page for cited in cited_pages for page in range(cited-2,cited+3)})

    selected=_owned_correction_source_pages([reason],anchors,available_pages)

    assert set(selected)==expected


@pytest.mark.parametrize('reason', [
    'The source supports retaining the omitted qualification.',
    'Source p. 99: this page is not available in the supplied source.',
    'The printed folio is 30, but no physical source page is identified.',
])
def test_nonlocatable_or_invalid_reviewer_note_falls_back_to_all_available_pages(reason):
    available_pages={4,5,6,19,20,21,22,35}

    selected=_owned_correction_source_pages([reason],{20},available_pages)

    assert set(selected)==available_pages
