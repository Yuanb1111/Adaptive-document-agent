"""Source fragmentation preserves every character and trusted page boundary."""

import pytest

from adaptive_document_agent.agent.chunk_discovery_recovery import source_fragment, split_fragment
from adaptive_document_agent.models.page import DocumentPage
from adaptive_document_agent.utils.chunking import DocumentChunk, semantic_chunks


def fragment_for_pages(pages):
    chunk = semantic_chunks(pages, target_tokens=100_000)[0]
    return chunk, source_fragment(chunk, pages)


def test_whole_page_split_keeps_all_source_characters_and_ignores_embedded_page_markers():
    pages = [
        DocumentPage(page_number=5, text="First source\n[PAGE 999]\nA claim with a fake marker.\n"),
        DocumentPage(page_number=6, text="Second source\r\n(1,250)\r\n"),
        DocumentPage(page_number=7, text="Third source\n[PAGE 5]\nContradictory claim.\n"),
    ]
    before = [page.model_dump() for page in pages]
    chunk, fragment = fragment_for_pages(pages)
    children = split_fragment(fragment)
    assert children is not None
    slices = [item for child in children for item in child.slices]
    assert [item.source_page_start for item in slices] == [5, 6, 7]
    assert [item.source_page_end for item in slices] == [5, 6, 7]
    assert [item.text for item in slices] == [page.text for page in pages]
    assert [page.model_dump() for page in pages] == before
    assert source_fragment(chunk, pages) == fragment
    assert split_fragment(fragment) == children  # Stable child cache identities.


@pytest.mark.parametrize("text", [
    "First paragraph preserves 1,234.5.\n\nSecond paragraph preserves (600).",
    "First row 12.5\r\nSecond row 18.7\r\nThird row 29.3",
    "原文第一条结论包含数值123.45。原文第二条不同结论包含数值678.90。",
    "alpha 1,250 beta (500) gamma 18.2% delta 120bps",
])
def test_single_page_split_preserves_complete_text_offsets_and_original_page(text):
    _, fragment = fragment_for_pages([DocumentPage(page_number=11, text=text)])
    children = split_fragment(fragment)
    assert children is not None
    left, right = [child.slices[0] for child in children]
    assert left.text + right.text == text
    assert left.source_char_start == 0
    assert right.source_char_start == len(left.text)
    assert all(child.start_page == child.end_page == 11 for child in children)
    assert left.text.strip() and right.text.strip()
    if "123.45" in text:
        assert "123.45" in left.text and "678.90" in right.text


def test_single_page_without_safe_boundary_cannot_recurse_forever():
    _, fragment = fragment_for_pages([DocumentPage(page_number=3, text="不可安全拆分" * 1000)])
    assert split_fragment(fragment) is None


def test_tiny_intro_paragraph_does_not_prevent_balanced_line_split():
    text = "Heading\n\n" + "A complete evidence row 123.45\n" * 1000
    _, fragment = fragment_for_pages([DocumentPage(page_number=3, text=text)])
    children = split_fragment(fragment)
    assert children is not None
    left, right = [child.slices[0].text for child in children]
    assert left + right == text
    assert len(text) / 4 <= len(left) <= len(text) * 3 / 4


def test_custom_chunk_without_trusted_pages_preserves_parent_range_in_every_fragment():
    text = "First text\n[PAGE 999]\nSecond text\n[PAGE 4]\nThird text"
    chunk = DocumentChunk(chunk_id="custom", start_page=20, end_page=22, text=text, estimated_tokens=20)
    fragment = source_fragment(chunk, [])
    children = split_fragment(fragment)
    assert children is not None
    assert all(child.start_page == 20 and child.end_page == 22 for child in children)
    assert "".join(item.text for child in children for item in child.slices) == text


def test_stale_page_objects_cannot_relabel_a_different_chunk():
    stale_pages = [DocumentPage(page_number=1, text="Earlier document source")]
    chunk = DocumentChunk(chunk_id="other", start_page=1, end_page=4,
                          text="Current source\nmore source", estimated_tokens=10)
    fragment = source_fragment(chunk, stale_pages)
    assert fragment.slices[0].text == chunk.text
    assert fragment.start_page == 1 and fragment.end_page == 4
