"""Bounded progress checks for newly discovered introduction review defects."""
from adaptive_document_agent.services.introduction_audience import selection_digest
from adaptive_document_agent.services.source_quotes import normalize_quote

BASE_SEMANTIC_REVIEWS = 3
MAX_SEMANTIC_REVIEWS = 5


class IntroductionRepairBudget:
    """Track literal review addresses, never decide truth or audience relevance."""

    def __init__(self, *, audit_cursor=0):
        self.seen_findings = {}
        self.rejected_candidates = set()
        self.meaning_origins = {}
        self.audit_cursor = audit_cursor

    def _track_revisions(self, review):
        """Follow validated edit addresses; wording and semantic judgments stay with the model."""
        for index in range(self.audit_cursor, len(review.plan_audits)):
            record = review.plan_audits[index]
            if 'introduction_meaning_resolution' in record:
                record = record['introduction_meaning_resolution']
                if record.get('status') != 'protocol_validated':
                    continue
            lineage = record.get('meaning_lineage')
            if lineage is None:
                continue
            origins = {}
            for current, previous in lineage.items():
                inherited = set()
                for address in previous:
                    inherited.update(self.meaning_origins.get(address, {address}))
                origins[current] = inherited or {f'addition-{index}:{current}'}
            self.meaning_origins = origins
        self.audit_cursor = len(review.plan_audits)

    def allow_repair(self, values, verdict, review, *, attempt: int) -> bool:
        self._track_revisions(review)
        # This is called only AFTER the independent verdict passes binding.
        # Different phrasing of a reason is not a new source-owned finding.
        # Several independently reviewed assertions can share a complete source
        # passage. Their ordinal IDs can change after a split or merge, so use
        # the bound assertion text to recognize it across review rounds.
        by_part = {d['part_id']: {m['meaning'] for m in d['required_meanings']} for d in values}
        signatures, novel, finding_origins = [], [], []
        for i, finding in enumerate(verdict.findings):
            key = (finding.kind, finding.issue_type, finding.part_id, normalize_quote(finding.source_quote))
            target = finding.current_meaning
            origins = self.meaning_origins.get(finding.meaning_id, {finding.meaning_id})
            finding_origins.append(sorted(origins))
            siblings = by_part[finding.part_id] - {target}
            prior = self.seen_findings.setdefault(key, [])
            # Detect a renumbered assertion by text and an in-place rewrite by
            # address. A reused address can identify a different assertion if
            # both assertions coexisted in one draft.
            if finding.issue_type != 'unspecified' and all(
                    target != old and (origins.isdisjoint(old_origins)
                                       or target in old_siblings or old in siblings)
                    for old_origins, old, old_siblings in prior):
                novel.append(i)
            prior.append((origins, target, siblings))
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
                finding_origin_ids=finding_origins,
                repair_allowed=allowed, reason=reason, semantic_approval=False)})
        return allowed
