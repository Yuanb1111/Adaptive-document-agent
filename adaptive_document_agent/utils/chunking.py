"""Page-aware semantic chunking without flattening document provenance."""

from pydantic import BaseModel, Field

from adaptive_document_agent.models.page import DocumentPage
from .ids import stable_id


class DocumentChunk(BaseModel):
    chunk_id: str
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    section_hints: list[str] = Field(default_factory=list)
    estimated_tokens: int = Field(ge=0)
    text: str


def semantic_chunks(pages: list[DocumentPage], *, target_tokens: int = 6_000) -> list[DocumentChunk]:
    """Build approximate token chunks while preserving page boundaries and headings."""
    if not pages:
        return []
    chunks: list[DocumentChunk] = []
    current: list[DocumentPage] = []
    current_tokens = 0
    for page in pages:
        estimate = max(1, len(page.text) // 4)
        if current and current_tokens + estimate > target_tokens:
            chunks.append(_build_chunk(current))
            current, current_tokens = [], 0
        current.append(page)
        current_tokens += estimate
    if current:
        chunks.append(_build_chunk(current))
    return chunks


def _build_chunk(pages: list[DocumentPage]) -> DocumentChunk:
    text = "\n\n".join(f"[PAGE {page.page_number}]\n{page.text}" for page in pages)
    hints: list[str] = []
    for page in pages:
        for line in page.text.splitlines():
            line = line.strip()
            if 3 <= len(line) <= 100 and (line.isupper() or line.istitle()):
                hints.append(line)
    return DocumentChunk(
        chunk_id=stable_id("chunk", pages[0].page_number, pages[-1].page_number, text[:100]),
        start_page=pages[0].page_number,
        end_page=pages[-1].page_number,
        section_hints=list(dict.fromkeys(hints))[:20],
        estimated_tokens=max(1, len(text) // 4),
        text=text,
    )

