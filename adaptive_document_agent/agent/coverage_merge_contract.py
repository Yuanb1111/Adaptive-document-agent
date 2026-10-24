"""Scope the merge ledger to proposed additions without restricting topic evidence."""
from pydantic import Field, create_model, model_validator


def scoped_merge_decisions(reviewed, requested, accepted):
    """Quarantine out-of-scope echoes of immutable choices, never new decisions."""
    from .coverage_delta_review import _decisions

    requested, accepted = tuple(requested), set(accepted)
    echoes = [d for d in reviewed.coverage_decisions
              if d.series_id in accepted and d.series_id not in requested]
    # Unknown IDs, missing requested decisions, duplicates and empty reasons
    # still fail. Echoes gain no authority over topics or accepted observations.
    local = _decisions(reviewed, [*requested, *(d.series_id for d in echoes)])
    return {sid: local[sid] for sid in requested}, echoes


def merge_response_model(requested, accepted=()):
    """Expose exact ledger IDs to every provider and validate them locally too."""
    from .topic_coverage_review import CoverageDecision, TopicCoverageReview

    ids = tuple(requested)
    accepted = frozenset(accepted)
    if not ids or len(set(ids)) != len(ids) or accepted.intersection(ids):
        raise ValueError('A coverage merge requires unique provisional series IDs.')
    decision = create_model('CoverageDecision', __base__=CoverageDecision,
        series_id=(str, Field(description='A proposed addition requiring a decision; not an accepted topic ID.',
                              json_schema_extra={'enum': list(ids)})))

    def exact_ledger(self):
        # Use the existing concise diagnostic instead of repeating a potentially
        # large enum in every Pydantic error. Known immutable-choice echoes are
        # retained raw here; only the full source-preserving merge can accept
        # their exclusion from the provisional ledger.
        scoped_merge_decisions(self, ids, accepted)
        return self

    # Preserve the operation name and its existing gateway reasoning policy.
    # Schema contents participate in the gateway cache identity independently.
    return create_model('TopicCoverageReview', __base__=TopicCoverageReview,
        coverage_decisions=(list[decision], Field(description=(
            'Exactly one include/omit decision per proposed addition. Previously accepted '
            'series remain in topics, but must not have ledger entries.'),
            json_schema_extra={'minItems': len(ids), 'maxItems': len(ids)})),
        __validators__={'exact_ledger': model_validator(mode='after')(exact_ledger)})
