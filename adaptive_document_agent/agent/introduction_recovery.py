"""Bounded progress checks for newly discovered introduction review defects."""
from adaptive_document_agent.services.introduction_audience import selection_digest
from adaptive_document_agent.services.source_quotes import normalize_quote

BASE_SEMANTIC_REVIEWS = 3
MAX_SEMANTIC_REVIEWS = 5


class IntroductionRepairBudget:
    """Track literal review addresses, never decide truth or audience relevance."""

    def __init__(self):
        self.seen_findings = {}
        self.rejected_candidates = set()

    def allow_repair(self, values, verdict, review, *, attempt: int) -> bool:
        # This is called only AFTER the independent verdict passes binding.
        # Different phrasing of a reason is not a new source-owned finding.
        # Several independently reviewed assertions can share a complete source
        # passage. Their ordinal IDs can change after a split or merge, so use
        # the bound assertion text to recognize it across review rounds.
        by_part = {d['part_id']: {m['meaning'] for m in d['required_meanings']} for d in values}
        signatures, novel = [], []
        for i, finding in enumerate(verdict.findings):
            key = (finding.kind, finding.issue_type, finding.part_id, normalize_quote(finding.source_quote))
            target = finding.current_meaning
            siblings = by_part[finding.part_id] - {target}
            prior = self.seen_findings.setdefault(key, [])
            # Detect a renumbered assertion by text and an in-place rewrite by
            # address. A reused address can identify a different assertion if
            # both assertions coexisted in one draft.
            if finding.issue_type != 'unspecified' and all(
                    target != old and (finding.meaning_id != address or target in old_siblings or old in siblings)
                    for address, old, old_siblings in prior):
                novel.append(i)
            prior.append((finding.meaning_id, target, siblings))
            signatures.append((*key, target))
        digest = selection_digest(review, values)
        state = digest, tuple(sorted(set(signatures)))
        repeated = state in self.rejected_candidates
        self.rejected_candidates.add(state)
        round_number = attempt + 1
        if round_number >= MAX_SEMANTIC_REVIEWS:
            reason = 'semantic_review_budget_exhausted'
        elif repeated:
            reason = 'unchanged_rejected_candidate_and_findings'
        elif round_number < BASE_SEMANTIC_REVIEWS:
            reason = 'standard_repair_budget'
        elif novel:
            reason = 'new_bound_source_findings'
        else:
            reason = 'no_new_bound_source_findings'
        allowed = reason in {'standard_repair_budget', 'new_bound_source_findings'}
        if round_number >= BASE_SEMANTIC_REVIEWS or repeated:
            review.plan_audits.append({'introduction_recovery_budget': dict(
                review_round=round_number, maximum_semantic_reviews=MAX_SEMANTIC_REVIEWS,
                candidate_digest=digest, novel_finding_indices=novel,
                repair_allowed=allowed, reason=reason, semantic_approval=False)})
        return allowed
