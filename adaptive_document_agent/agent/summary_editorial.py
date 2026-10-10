"""Compact source references for editorial planning over a complete Summary."""
from pydantic import BaseModel, ConfigDict, Field

from adaptive_document_agent.models.summary import SummaryPartDecision, SummarySlideItem, SummarySlidePage
from adaptive_document_agent.utils.ids import stable_id


class EditorialItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fact_id: str
    label: str = Field(min_length=1, max_length=60)
    # Transport copy can exceed the final box limit. Pagination below retains
    # its complete wording instead of invalidating an otherwise complete plan.
    text: str = Field(min_length=1, max_length=6000)


class EditorialPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=65)
    source_section: str = Field(min_length=1, max_length=160)
    items: list[EditorialItem] = Field(min_length=1, max_length=4)


class SummaryEditorialDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = ''
    name_fact_id: str = ''
    summary_pages: list[EditorialPage] = Field(default_factory=list, max_length=8)
    summary_decisions: list[SummaryPartDecision] = Field(default_factory=list)


def editorial_parts(parts):
    payload, catalog = [], {}
    for part in parts:
        row = part.model_dump(mode='json', exclude={'source_text', 'block_id', 'start_line', 'end_line'})
        row['facts'] = []
        for index, fact in enumerate(part.facts):
            identifier = stable_id('summary_fact', part.id, index)
            catalog[identifier] = (part, fact)
            row['facts'].append({'id': identifier, **fact.model_dump(mode='json')})
        payload.append(row)
    return payload, catalog


def expand_editorial(draft, catalog, response_model):
    """Fill literal quotes/pages in Python; the model chooses claims and grouping."""
    pages = []
    for page in draft.summary_pages:
        items = []
        for item in page.items:
            if item.fact_id not in catalog:
                raise ValueError('Summary editorial item cites an unknown reading fact: ' + item.fact_id)
            part, fact = catalog[item.fact_id]
            pieces = split_editorial_copy(item.text)
            from hashlib import sha256
            digest = sha256(item.text.encode('utf-8')).hexdigest() if len(pieces)>1 else ''
            group = stable_id('summary_copy', page.id, item.fact_id, item.text) if len(pieces)>1 else ''
            for index, text in enumerate(pieces):
                items.append(SummarySlideItem(label=item.label, text=text, part_ids=[part.id],
                    source_quote=fact.source_quote, source_pages=list(fact.source_pages),
                    continuation_group=group, continuation_index=index,
                    continuation_count=len(pieces), continuation_digest=digest))
        for offset in range(0, len(items), 4):
            values = page.model_dump(exclude={'items'})
            if offset:
                values['id'] = stable_id('summary_continuation', page.id, offset)
            pages.append(SummarySlidePage(**values, items=items[offset:offset+4]))
    values = {'summary_pages': pages, 'summary_decisions': draft.summary_decisions, 'name': draft.name}
    if draft.name:
        if draft.name_fact_id not in catalog:
            raise ValueError('Company identity cites an unknown Summary reading fact')
        _, fact = catalog[draft.name_fact_id]
        values.update(name_quote=fact.source_quote, name_page=fact.source_pages[0])
    elif draft.name_fact_id:
        raise ValueError('An identity fact reference requires its literal company name')
    return response_model(**values)


def split_editorial_copy(text, limit=180):
    """Layout-only splits; concatenation preserves every source-authored word."""
    pieces = []
    while len(text) > limit:
        # Prefer a sentence or word boundary, never omit punctuation or words.
        import re
        # Do not split decimal punctuation or a monetary/date token. A whole
        # long identifier may be split for layout; group validation below still
        # verifies the original complete claim, never its disconnected digits.
        boundaries = [m.end() for m in re.finditer(r'\s+|[。；!?]|\.(?!\d)',text[:limit])]
        end = max((i for i in boundaries if i >= limit//2), default=limit)
        pieces.append(text[:end])
        text = text[end:]
    if text:
        pieces.append(text)
    return pieces
