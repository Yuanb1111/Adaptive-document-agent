"""Bounded progress checks for newly discovered introduction review defects."""
from adaptive_document_agent.services.introduction_audience import selection_digest
from adaptive_document_agent.services.source_quotes import normalize_quote

BASE_SEMANTIC_REVIEWS = 3
MAX_SEMANTIC_REVIEWS = 5


class IntroductionRepairBudget:
    """Track literal review addresses, never decide truth or audience relevance."""

    def __init__(self):
        self.seen_findings = set()
        self.rejected_candidates = set()

    def allow_repair(self, values, verdict, review, *, attempt: int) -> bool:
        # This is called only AFTER the independent verdict passes binding.
        # Different phrasing of a reason is not a new source-owned finding.
        signatures = [(f.kind, f.issue_type, f.part_id, normalize_quote(f.source_quote))
                      for f in verdict.findings]
        novel = [i for i, key in enumerate(signatures)
                 if key not in self.seen_findings and key[1] != 'unspecified']
        digest = selection_digest(review, values)
        state = digest, tuple(sorted(set(signatures)))
        repeated = state in self.rejected_candidates
        self.seen_findings.update(signatures)
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
