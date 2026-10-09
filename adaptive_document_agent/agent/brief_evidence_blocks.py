"""Exact source references for briefing transport; persisted quotes stay literal."""
from copy import deepcopy
import re

from pydantic import BaseModel, ConfigDict, Field, create_model
from adaptive_document_agent.models.executive_brief import BriefQuote, ExecutiveBriefItem, ExecutiveBrief


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ref: str = Field(min_length=1, max_length=80)


# Literal quotes remain accepted for compatible clients, but the prompt asks
# for IDs. Both paths pass the same source, unit, period and condition gates.
ReferencedBriefItem = create_model('ReferencedBriefItem', __base__=ExecutiveBriefItem,
    evidence=(list[EvidenceReference | BriefQuote], Field(min_length=1, max_length=4)))
ReferencedBrief = create_model('ExecutiveBrief', __base__=ExecutiveBrief,
    items=(list[ReferencedBriefItem], Field(min_length=1, max_length=7)))


def evidence_blocks(excerpts):
    """Partition every supplied passage without dropping words or qualifications."""
    blocks = {}
    for page, text in excerpts.items():
        for passage in text.split('[SEPARATE SOURCE PASSAGE]'):
            remaining = passage.strip()
            while remaining:
                cut = min(1600, len(remaining))
                if cut < len(remaining):
                    # Prefer a paragraph/line boundary, then a word boundary.
                    breaks = [m.end() for m in re.finditer(r'\n\s*\n|\n', remaining[:cut]) if m.end() >= cut * .6]
                    cut = max(breaks) if breaks else remaining.rfind(' ', 8, cut + 1)
                    if cut < 8:
                        cut = 1600
                piece = remaining[:cut].strip()
                rest = remaining[cut:].strip()
                if rest and len(rest) < 8 and len(piece) + len(rest) + 1 <= 1800:
                    piece, rest = remaining, ''
                if piece:
                    identifier = f'p{page}_b{len(blocks) + 1}'
                    blocks[identifier] = {'page': page, 'text': piece}
                remaining = rest
    return blocks


def expand_item(value, blocks):
    if not isinstance(value, dict) or not isinstance(value.get('evidence'), list):
        return value
    result = deepcopy(value)
    result['evidence'] = [deepcopy(blocks[q['ref']])
        if isinstance(q, dict) and set(q) == {'ref'} and isinstance(q['ref'], str) and q['ref'] in blocks else q
        for q in value['evidence']]
    return result


def expand_brief(value, blocks):
    return {**value, 'items': [expand_item(item, blocks) for item in value['items']]}
