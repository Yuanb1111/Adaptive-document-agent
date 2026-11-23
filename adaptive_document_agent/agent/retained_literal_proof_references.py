"""Exact, page-bound quote references for compact retained-copy transport."""
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adaptive_document_agent.models.executive_brief import BriefQuote


class LiteralProofReference(BaseModel):
    """Reference one immutable source passage without retranscribing its text."""

    model_config = ConfigDict(extra='forbid')
    passage_id: str = Field(min_length=1, max_length=80)


_PARAGRAPH_GAP = re.compile(r"\r?\n(?:[ \t]*\r?\n)+")


def _paragraph_spans(text: str):
    """Yield trimmed nonempty paragraphs with exact offsets into page text."""
    cursor = 0
    for gap in _PARAGRAPH_GAP.finditer(text):
        start, end = cursor, gap.start()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            yield start, end
        cursor = gap.end()
    start, end = cursor, len(text)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        yield start, end


def _exact_chunks(paragraph: str) -> list[tuple[int, str]]:
    """Return exact source offsets for splitter parts, or no catalog entries."""
    from adaptive_document_agent.services.source_quotes import split_literal_quote

    try:
        parts = split_literal_quote(paragraph)
    except ValueError:
        return []
    located = []
    search_from = 0
    for part in parts:
        start = paragraph.find(part, search_from)
        if start < 0:
            # Never reconstruct normalized text or guess where it came from.
            return []
        located.append((start, part))
        search_from = start + len(part)
    return located


def literal_proof_catalog(source_pages):
    """Return exact passage quotes and compact ID/offset metadata.

    ``source_pages`` is the page-preserving list of ``{page, text, ...}``
    records already supplied to compact-copy work. No text is normalized or
    searched approximately; every quote is sliced directly from its page.
    """
    passages: dict[str, BriefQuote] = {}
    wire_rows: list[dict] = []
    seen_pages = set()
    for source in source_pages:
        if not isinstance(source, dict):
            raise ValueError('A source page record must be an object')
        page, text = source.get('page'), source.get('text')
        if (not isinstance(page, int) or isinstance(page, bool) or page < 1
                or not isinstance(text, str) or page in seen_pages):
            raise ValueError('Source pages need unique positive physical page numbers and literal text')
        seen_pages.add(page)
        for paragraph_start, paragraph_end in _paragraph_spans(text):
            paragraph = text[paragraph_start:paragraph_end]
            for local_start, literal in _exact_chunks(paragraph):
                start, end = paragraph_start + local_start, paragraph_start + local_start + len(literal)
                if len(literal) < 8:
                    continue
                try:
                    quote = BriefQuote(page=page, text=literal)
                except ValidationError as exc:
                    raise ValueError('A source paragraph cannot form a bounded literal quote') from exc
                passage_id = f'p{page}_s{start}_e{end}'
                passages[passage_id] = quote
                wire_rows.append(dict(passage_id=passage_id, page=page, start=start, end=end,
                                      first_words=' '.join(literal.split()[:8])[:120]))
    return passages, wire_rows


def resolve_literal_proof(value, passages: dict[str, BriefQuote]) -> dict:
    """Expand a strict passage reference; leave legacy literal proofs untouched."""
    if isinstance(value, LiteralProofReference):
        ref = value.passage_id
        if ref not in passages:
            raise ValueError(f'Unknown literal proof reference {ref!r}')
        return passages[ref].model_dump(mode='json')
    if isinstance(value, dict) and 'passage_id' in value:
        try:
            ref = LiteralProofReference.model_validate(value).passage_id
        except ValidationError as exc:
            raise ValueError('Malformed literal proof reference') from exc
        if ref not in passages:
            raise ValueError(f'Unknown literal proof reference {ref!r}')
        return passages[ref].model_dump(mode='json')
    return value


def resolve_source_context_proof(value, passages, *, remaining_depth=2):
    """Expand references inside the existing typed proof nesting limit."""
    if not isinstance(value, dict) or 'continuation_quotes' not in value:
        return resolve_literal_proof(value, passages)
    nested = value['continuation_quotes']
    if not remaining_depth or not isinstance(nested, list) or len(nested) > 3:
        return value
    root = {key: item for key, item in value.items() if key != 'continuation_quotes'}
    return {**resolve_literal_proof(root, passages), 'continuation_quotes': [
        resolve_source_context_proof(item, passages, remaining_depth=remaining_depth - 1)
        for item in nested]}


def rejected_proof_reference_candidates(quotes, source_pages, passages):
    """Point to exact original reading aids without repairing an invalid proof."""
    from adaptive_document_agent.services.literal_quote_feedback import source_passage_hint
    from adaptive_document_agent.services.source_quotes import normalize_quote

    sources={source['page']:source['text'] for source in source_pages}
    identifiers={}
    for passage_id,quote in passages.items():
        identifiers.setdefault((quote.page,quote.text),[]).append(passage_id)
    candidates=[]
    for index,quote in enumerate(quotes,1):
        source=sources.get(quote.page)
        if not source or normalize_quote(quote.text) in normalize_quote(source):
            continue
        paragraph=source_passage_hint(quote.text,source)
        matches=identifiers.get((quote.page,paragraph),[])
        if len(matches)==1:
            candidates.append(dict(rejected_quote_index=index,page=quote.page,passage_id=matches[0]))
    return candidates
