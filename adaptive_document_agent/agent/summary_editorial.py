"""Compact source references for editorial planning over a complete Summary."""
from pydantic import BaseModel, ConfigDict, Field

from adaptive_document_agent.models.summary import SummaryPartDecision, SummarySlideItem, SummarySlidePage
from adaptive_document_agent.utils.ids import stable_id


class EditorialItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fact_id: str
    label: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=180)


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
            items.append(SummarySlideItem(label=item.label, text=item.text, part_ids=[part.id],
                source_quote=fact.source_quote, source_pages=list(fact.source_pages)))
        pages.append(SummarySlidePage(**page.model_dump(exclude={'items'}), items=items))
    values = {'summary_pages': pages, 'summary_decisions': draft.summary_decisions, 'name': draft.name}
    if draft.name:
        if draft.name_fact_id not in catalog:
            raise ValueError('Company identity cites an unknown Summary reading fact')
        _, fact = catalog[draft.name_fact_id]
        values.update(name_quote=fact.source_quote, name_page=fact.source_pages[0])
    elif draft.name_fact_id:
        raise ValueError('An identity fact reference requires its literal company name')
    return response_model(**values)
