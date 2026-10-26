"""Expose source-specific choices when duplicate disclosures disagree in scope."""
from collections import defaultdict

from adaptive_document_agent.document_model.series import source_context_key
from adaptive_document_agent.validation.presentation_evidence_alignment import _same_reported_fact


def distinct_source_series(group):
    """Split a candidate only when overlapping source facts are not exact peers.

    Equal numeric cells with different audit/definition/date/unit metadata are
    not interchangeable. Keep complete source contexts selectable so the model
    can choose one; do not choose a preferred source or alter any observation.
    """
    contexts, periods = defaultdict(list), defaultdict(list)
    for observation in group:
        contexts[source_context_key(observation)].append(observation)
        if observation.period:
            periods[observation.period].append(observation)
    if len(contexts) > 1 and any(
        source_context_key(a) != source_context_key(b) and not _same_reported_fact(a, b)
        for peers in periods.values() for i, a in enumerate(peers) for b in peers[i+1:]
    ):
        return list(contexts.values())
    return [group]
