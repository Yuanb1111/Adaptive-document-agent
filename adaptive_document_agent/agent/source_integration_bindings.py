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
    'These addresses establish only which text to inspect, never semantic approval. '
    'audience_text includes the published label, body and comparison_table cells. The table is '
    'visible audience copy, not private evidence or a footnote. Review its complete rows alongside '
    'the body; a material qualification present there is not omitted merely because it is absent '
    'from the body paragraph. Still reject incomplete or ambiguous conditions, wrong attribution '
    'or unsupported scope, and check the cells against their own source quotations. Independently '
    'assess material coverage of each section against the pages enumerated in its check.pages. '
    'This is a concise briefing, not an exhaustive inventory of each checked page. Reject an '
    'omission when it changes interpretation of an actual conclusion or the assessment of a '
    'material source issue; explain that effect. Do not require every contextual number or '
    'routine detail merely because it appears nearby. Material assumptions, counterevidence '
    'and the stated basis of a qualified judgment still need faithful audience coverage. '
    'Require every material qualification on those pages. When judging an omission, identify the '
    'section page that supplies it. Other pages quoted by the original brief can explain existing '
    'claims but do not enlarge the chosen section range or require new conclusions from those pages. '
    'check whether those exact items carry the source meaning and whether additions are material '
    'and supported. Do not reinterpret include as covered or look up addition indices in the '
    'shorter original brief. Apply the same evidence rules as the writer. When a PDF table '
    'is flattened, require a numerical estimate only if its measure, amount and unit are '
    'unambiguously bound by the source. Otherwise assess whether the brief conveys the '
    'material qualitative finding and uncertainty. Do not reconstruct cells from proximity. '
    'verified_quantity_columns supplies amount/unit pairs checked from original column geometry, '
    'even when has_structured_tables is false. Verify their measure/project ownership and all '
    'qualifications against the full source; require the item to quote all evidence_lines for each '
    'used pair. Geometry proves the unit binding, not semantic meaning or approval. ')


def merged_review_context(context: dict, draft: SourceIntegrationDraft, merged: ExecutiveBrief) -> dict:
    """Preserve full sources and content; expose exact, prevalidated index ownership."""
    review = deepcopy(context)
    from adaptive_document_agent.models.executive_brief import brief_claim_text
    original = review.pop('current_brief')
    original_count = len(original['items'])
    review.update(original_brief=original, original_brief_item_count=original_count,
        merged_brief_title=merged.title,
        merged_brief_items=[dict(index=index,
            origin='original' if index < original_count else 'addition',
            audience_text=brief_claim_text(item),
            item=item.model_dump(mode='json')) for index, item in enumerate(merged.items)],
        resolved_source_bindings=[dict(section_id=decision.section_id,
            disposition=decision.disposition,
            items=[dict(index=index, origin='original' if index < original_count else 'addition')
                   for index in decision.brief_item_indexes]) for decision in draft.decisions])
    return review


def bind_unique_inclusions(draft, checks, original_count):
    """Recover an omitted address only for a one-to-one, exclusively cited section.

    The writer already chose include and wrote the addition. The independent
    reviewer still decides whether the proposed conclusion covers that section.
    """
    addresses = {}
    claimed = {i for decision in draft.decisions for i in decision.brief_item_indexes}
    exclusive = {}
    for decision in draft.decisions:
        sid = decision.section_id
        if decision.disposition != 'include' or sid not in checks:
            continue
        owned = set(checks[sid].pages)
        other = {p for key, check in checks.items() if key != sid for p in check.pages}
        candidates = [(original_count + i, {q.page for q in item.evidence})
                      for i, item in enumerate(draft.additions) if any(q.page in owned for q in item.evidence)]
        if len(candidates) == 1:
            index, pages = candidates[0]
            if pages <= owned - other:
                exclusive[sid] = index
            if sid in exclusive and not decision.brief_item_indexes and index not in claimed:
                decision.brief_item_indexes = [index]
                addresses[sid] = index
                claimed.add(index)
    # Only a whole, bijective one-based ledger ending beyond the valid range
    # establishes an alternate numbering convention. Never shift a mixed list.
    expected = set(range(original_count, original_count + len(draft.additions)))
    if (not addresses and expected and set(exclusive.values()) == expected
            and len(exclusive) == len(expected) == len(draft.decisions)
            and all(d.section_id in exclusive and d.brief_item_indexes == [exclusive[d.section_id] + 1]
                    for d in draft.decisions)):
        for decision in draft.decisions:
            decision.brief_item_indexes = [exclusive[decision.section_id]]
        return exclusive
    return addresses


def keep_accepted_dispositions(previous, verdicts, revised, original_count):
    """Keep independently accepted items only at unchanged, exclusively owned addresses."""
    old = {d.section_id: d for d in previous.decisions}
    kept = []
    for index, decision in enumerate(revised.decisions):
        sid = decision.section_id
        prior = old.get(sid)
        if sid not in verdicts or not verdicts[sid].accepted or prior is None:
            continue
        additions = {i for i in prior.brief_item_indexes if i >= original_count}
        if decision.brief_item_indexes != prior.brief_item_indexes:
            # Original items are immutable. Extra references to them cannot
            # move a previously accepted, separately owned addition.
            extra = set(decision.brief_item_indexes) - set(prior.brief_item_indexes)
            if (not additions or not extra or any(i < 0 or i >= original_count for i in extra)
                    or not set(prior.brief_item_indexes) <= set(decision.brief_item_indexes)):
                continue
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
