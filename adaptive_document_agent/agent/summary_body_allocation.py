"""Reallocate body copy without regenerating previously authored appendices."""
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field

from .compact_summary import SummarySynthesisBodyPage
from .summary_content_repair import ItemAddition
from .summary_draft_protocol import author_draft, SummaryDraftProtocolError


class SummaryBodyAllocation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: list[SummarySynthesisBodyPage] = Field(min_length=1, max_length=5)
    additions: list[ItemAddition] = Field(default_factory=list, max_length=32)


def reallocate_body(gateway, draft, messages, schema, audit, *, cancelled=None):
    instruction = {'role': 'user', 'content':
        'Return only a concise replacement body and any supporting additions to existing appendix '
        'groups. Python retains every existing appendix paragraph unchanged; do not reproduce, '
        'summarize or replace those appendices. Their details already count toward source coverage. '
        'Use zero-based page_index from the supplied draft for additions, targeting only pages whose '
        'placement is appendix. Preserve the body opening. Keep the new body short enough for the '
        'reported physical budget: prefer two concise paragraphs per body group, each around '
        '180 Latin characters or 90 CJK characters. Move detail into appendix additions when needed. '
        'Keep exact fact_ids and every supported claim across the new body, retained appendices and '
        'additions. Never replace numerical tables with descriptions of their existence.'}
    allocation = author_draft(gateway, messages + [instruction], SummaryBodyAllocation, audit,
                              cancelled=cancelled)
    audit['body_allocation'] = allocation.model_dump(mode='json')
    data = deepcopy(draft.model_dump(mode='json'))
    for addition in allocation.additions:
        index = addition.page_index
        if not 0 <= index < len(data['pages']) or data['pages'][index].get('placement') != 'appendix':
            raise SummaryDraftProtocolError('Body allocation additions must target existing appendix groups')
        data['pages'][index]['items'].append(addition.item.model_dump(mode='json'))
    data['pages'] = [p.model_dump(mode='json') for p in allocation.body] + [
        page for page in data['pages'] if page.get('placement') == 'appendix']
    try:
        return schema.model_validate(data)
    except ValueError as exc:
        raise SummaryDraftProtocolError('Body allocation exceeds logical group capacity') from exc
