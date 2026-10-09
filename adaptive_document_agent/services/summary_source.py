"""Lossless page-bound source blocks for introductory reading; no semantic ranking."""
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.summary import SummarySourceBlock
from adaptive_document_agent.utils.ids import stable_id
from .company_summary import summary_page_numbers

MAX_SUMMARY_CHARACTERS = 300_000
BLOCK_CHARACTERS = 6500
BATCH_CHARACTERS = 12_000


def summary_scope(result: PipelineResult, ranges) -> list[int]:
    """Running headers/outline are retrieval anchors, not semantic topic choices."""
    pages = set(summary_page_numbers(result.document))
    import re
    for section in result.document.outline:
        if re.fullmatch(r'(?i)(?:summary|executive\s+summary|概要|摘要)', section.title.strip()):
            pages.update(range(section.start_page, section.end_page + 1))
    for span in ranges:
        if span.end_page < span.start_page or span.end_page > result.document.page_count:
            raise ValueError('Summary scope cites an invalid page range')
        pages.update(range(span.start_page, span.end_page + 1))
    available = {p.page_number: p for p in result.document.pages}
    if not pages <= available.keys():
        raise ValueError('Summary scope contains unavailable pages')
    if any(not available[p].text.strip() for p in pages):
        raise ValueError('Summary scope has unreadable pages; complete reading requires OCR')
    return sorted(pages)


def source_blocks(result: PipelineResult, pages: list[int]) -> list[SummarySourceBlock]:
    selected = {p.page_number: p.text for p in result.document.pages if p.page_number in pages}
    if sum(map(len, selected.values())) > MAX_SUMMARY_CHARACTERS:
        raise ValueError('Complete Summary exceeds the bounded reading budget; no source was sampled')
    blocks = []
    for page in pages:
        text = selected[page]
        start = 0
        while start < len(text):
            end = min(start + BLOCK_CHARACTERS, len(text))
            if end < len(text):
                newline = text.rfind('\n', start, end)
                if newline >= start:
                    end = newline + 1
            blocks.append(SummarySourceBlock(id=stable_id('summary_block', page, start, end, text[start:end]),
                page=page, char_start=start, char_end=end, text=text[start:end]))
            start = end
    return blocks


def reading_batches(blocks: list[SummarySourceBlock]) -> list[list[SummarySourceBlock]]:
    batches, batch, size = [], [], 0
    for block in blocks:
        if batch and size + len(block.text) > BATCH_CHARACTERS:
            batches.append(batch)
            batch, size = [], 0
        batch.append(block)
        size += len(block.text)
    if batch:
        batches.append(batch)
    return batches
