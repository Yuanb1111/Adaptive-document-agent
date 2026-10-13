"""Apply explicit paragraph revisions without regenerating accepted surroundings."""
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field

from .compact_summary import CompactSummaryItem
from .summary_draft_protocol import author_draft


class ItemReplacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page_index: int = Field(ge=0)
    item_index: int = Field(ge=0)
    replacement: CompactSummaryItem


class ItemAddition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page_index: int = Field(ge=0)
    item: CompactSummaryItem


class TitleReplacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page_index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=65)


class SummarySynthesisRevision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    replacements: list[ItemReplacement] = Field(default_factory=list, max_length=64)
    additions: list[ItemAddition] = Field(default_factory=list, max_length=16)
    titles: list[TitleReplacement] = Field(default_factory=list, max_length=12)


def apply_content_revision(draft, revision, schema):
    data = deepcopy(draft.model_dump(mode='json'))
    seen = set()
    def page(index):
        if not 0 <= index < len(data['pages']):
            raise ValueError('Content repair references an unknown logical page')
        return data['pages'][index]
    for edit in revision.replacements:
        target = page(edit.page_index)
        key = edit.page_index, edit.item_index
        if key in seen or not 0 <= edit.item_index < len(target['items']):
            raise ValueError('Content repair references a duplicate or unknown item')
        seen.add(key)
        target['items'][edit.item_index] = edit.replacement.model_dump(mode='json')
    for addition in revision.additions:
        page(addition.page_index)['items'].append(addition.item.model_dump(mode='json'))
    titles = set()
    for edit in revision.titles:
        if edit.page_index in titles:
            raise ValueError('Content repair repeats a title target')
        titles.add(edit.page_index)
        page(edit.page_index)['title'] = edit.title
    corrected = schema.model_validate(data)
    if corrected == draft:
        raise ValueError('Content repair repeated the rejected draft without correcting its failures')
    return corrected


def revise_content(gateway, draft, messages, schema, audit, *, cancelled=None):
    instruction = {'role': 'user', 'content':
        'Return only targeted revisions to previous_draft, using zero-based logical page_index and '
        'item_index from that draft (not rendered slide IDs). Fix the reported source or meaning '
        'errors. Replace only affected paragraphs and their exact fact_ids. Keep all other paragraphs '
        'unchanged; do not repeat the whole draft. Preserve each corrected paragraph\'s already '
        'supported information while adding missing attribution, material qualifications or evidence. '
        'Add a paragraph to an existing logical group only when an omitted source part needs it. '
        'When supporting appendix groups exist, use additions to those groups for missing definitions, '
        'qualifications, categories, figures and reporting periods. Keep the concise body unchanged '
        'unless its opening or an actual body claim is specifically rejected. Do not expand body '
        'paragraphs with long lists: that would trigger another layout rewrite and risk losing accepted '
        'details. Prefer adding the missing meaning alongside existing copy rather than replacing '
        'paragraphs that already cover other supported facts. An attribution correction must preserve '
        'the existing paragraph and all its supported details and fact IDs. '
        'Use titles only to fix a reported title error. Do not change identity, placement or ordering. '
        'Use the full supplied source catalog for exact fact IDs; never invent them. '
        'All revised copy will undergo full source, numeric, pagination and independent meaning checks.'}
    revision = author_draft(gateway, messages + [instruction], SummarySynthesisRevision, audit,
                            cancelled=cancelled)
    audit['content_revision'] = revision.model_dump(mode='json')
    return apply_content_revision(draft, revision, schema)
