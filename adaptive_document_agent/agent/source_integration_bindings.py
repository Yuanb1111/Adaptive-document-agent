"""Make validated merged-brief addresses explicit to the independent reviewer."""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    from .source_integration_review import SourceIntegrationDraft


MERGED_BRIEF_INSTRUCTIONS = (
    'brief_item_indexes address the zero-based merged_brief_items ledger, not original_brief. '
    'The ledger lists every original and proposed added item with its exact index and origin. '
    'An include decision must bind an addition; an addition is not missing merely because '
    'its index is at or above original_brief_item_count. A covered decision binds an original '
    'item. resolved_source_bindings supplies the already validated addresses for each section. '
    'These addresses establish only which text to inspect, never semantic approval: independently '
    'assess material coverage of each section against the pages enumerated in its check.pages. '
    'Require every material qualification on those pages. When judging an omission, identify the '
    'section page that supplies it. Other pages quoted by the original brief can explain existing '
    'claims but do not enlarge the chosen section range or require new conclusions from those pages. '
    'check whether those exact items carry the source meaning and whether additions are material '
    'and supported. Do not reinterpret include as covered or look up addition indices in the '
    'shorter original brief. ')


def merged_review_context(context: dict, draft: SourceIntegrationDraft, merged: ExecutiveBrief) -> dict:
    """Preserve full sources and content; expose exact, prevalidated index ownership."""
    review = deepcopy(context)
    original = review.pop('current_brief')
    original_count = len(original['items'])
    review.update(original_brief=original, original_brief_item_count=original_count,
        merged_brief_title=merged.title,
        merged_brief_items=[dict(index=index,
            origin='original' if index < original_count else 'addition',
            item=item.model_dump(mode='json')) for index, item in enumerate(merged.items)],
        resolved_source_bindings=[dict(section_id=decision.section_id,
            disposition=decision.disposition,
            items=[dict(index=index, origin='original' if index < original_count else 'addition')
                   for index in decision.brief_item_indexes]) for decision in draft.decisions])
    return review


def keep_accepted_dispositions(previous, verdicts, revised, original_count):
    """Keep independently accepted items only at unchanged, exclusively owned addresses."""
    old = {d.section_id: d for d in previous.decisions}
    kept = []
    for index, decision in enumerate(revised.decisions):
        sid = decision.section_id
        prior = old.get(sid)
        if sid not in verdicts or not verdicts[sid].accepted or prior is None:
            continue
        if decision.brief_item_indexes != prior.brief_item_indexes:
            continue
        additions = {i for i in prior.brief_item_indexes if i >= original_count}
        if any(i - original_count >= len(revised.additions) for i in additions):
            continue
        if any(additions.intersection(d.brief_item_indexes)
               for draft in (previous, revised) for d in draft.decisions if d.section_id != sid):
            continue
        revised.decisions[index] = prior.model_copy(deep=True)
        for i in additions:
            revised.additions[i - original_count] = previous.additions[i - original_count].model_copy(deep=True)
        kept.append(sid)
    return kept
