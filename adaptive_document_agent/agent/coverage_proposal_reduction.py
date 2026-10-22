"""Source-complete semantic reduction before an oversized coverage synthesis."""
from .coverage_review_context import delta_context, encode, merge_context
from .coverage_merge_encoding import encode_merge_context


def reduce_proposals(compact, original, proposed, decisions, handles, *, request, audit,
                     characters, decision_limit):
    """The model, never a Python rank or sample, narrows provisional additions.

    Each reduction sees every point and qualification of its requested series.
    Original accepted facts are immutable; all omitted proposals keep a model
    reason. Nothing is committed until the ordinary full-fact merge succeeds.
    """
    from .coverage_delta_review import TopicCoverageDelta, _decisions

    def size(ids):
        return len(encode_merge_context(merge_context(compact, original, ids, handles)))

    current = list(proposed)
    for level in range(3):
        if size(current) <= characters:
            return current
        groups, offset = [], 0
        while offset < len(current):
            group = []
            while offset < len(current) and len(group) < decision_limit:
                trial = [*group, current[offset]]
                if len(encode(delta_context(compact, original, trial))) > int(characters * .80):
                    break
                group = trial
                offset += 1
            if not group:
                raise ValueError('A complete coverage proposal exceeds the reduction context budget.')
            groups.append(group)
        kept = []
        for position, group in enumerate(groups):
            remaining = [sid for later in groups[position:] for sid in later]
            # Earlier decisions may already make the complete merge fit. The
            # remaining proposals were reviewed in the first pass; they need
            # no additional omission merely to meet a per-batch percentage.
            if size([*kept, *remaining]) <= characters:
                return [*kept, *remaining]
            context = delta_context(compact, original, group)
            context['hierarchical_reduction'] = dict(level=level + 1,
                purpose='Select the most material complementary evidence for one bounded audience report.',
                source_scope='All requested points and qualifications are supplied; other groups are deferred.',
                target_merge_context_characters=characters,
                current_merge_context_characters=size([*kept, *remaining]),
                target_retained_context_characters=max(1, len(encode(context)) // 2))
            entry = dict(level=level + 1, series_ids=group, context_characters=len(encode(context)))
            audit.setdefault('reductions', []).append(entry)

            def validate(reply):
                local = _decisions(reply, group)
                # Importance is a semantic decision. Fixed context overhead
                # can make a small batch unable to meet a local shrink ratio.
                # Enforce the actual complete merge capacity after the level.
                return local

            local = request(context, TopicCoverageDelta, entry, validate)
            decisions.update(local)
            kept.extend(sid for sid in group if local[sid].decision == 'include')
        if len(kept) >= len(current):
            raise ValueError('Coverage proposal reduction made no progress; review remains incomplete.')
        current = kept
    if size(current) > characters:
        raise ValueError('Coverage synthesis remains oversized after bounded semantic reduction.')
    return current
