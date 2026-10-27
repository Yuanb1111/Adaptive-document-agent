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
