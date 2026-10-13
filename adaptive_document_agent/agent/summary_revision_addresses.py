"""Explicit edit addresses and schema constraints for targeted content repair."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from .compact_summary import CompactSummaryItem


def revision_addresses(draft):
    groups = {f'g{p}': p for p in range(len(draft.pages))}
    items = {f'g{p}_i{i}': (p, i) for p, page in enumerate(draft.pages)
             for i in range(len(page.items))}
    item_id = Literal[tuple(items)]
    group_id = Literal[tuple(groups)]
    support = [key for key, p in groups.items() if draft.pages[p].placement == 'appendix']
    addition_id = Literal[tuple(support or groups)]
    class Strict(BaseModel):
        model_config = ConfigDict(extra='forbid')
    replacement = create_model('ParagraphReplacement', __base__=Strict,
        item_id=(item_id, ...), replacement=(CompactSummaryItem, ...))
    addition = create_model('ParagraphAddition', __base__=Strict,
        group_id=(addition_id, ...), item=(CompactSummaryItem, ...))
    title = create_model('GroupTitleReplacement', __base__=Strict,
        group_id=(group_id, ...), title=(str, Field(min_length=1, max_length=65)))
    schema = create_model('SummarySynthesisRevision', __base__=Strict,
        replacements=(list[replacement], Field(default_factory=list, max_length=64)),
        additions=(list[addition], Field(default_factory=list, max_length=16)),
        titles=(list[title], Field(default_factory=list, max_length=12)))
    payload = [dict(group_id=key, title=draft.pages[p].title, placement=draft.pages[p].placement,
        items=[dict(item_id=f'g{p}_i{i}', **item.model_dump(mode='json'))
               for i, item in enumerate(draft.pages[p].items)]) for key, p in groups.items()]
    return schema, payload, groups, items
