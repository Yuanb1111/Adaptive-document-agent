"""Expose the latest exact numeric change without deciding its analytical meaning."""
from decimal import Decimal

from adaptive_document_agent.document_model import group_comparable_series, canonical_series_partition_key
from adaptive_document_agent.validation.claim_validator import are_observations_compatible


def latest_numeric_intervals(observations):
    observations = list(observations)
    incomplete = {canonical_series_partition_key(o) for o in observations
                  if o.value is None or o.validation_status != 'valid' or o.anomaly_notes or not o.evidence}
    intervals = []
    for ordered in group_comparable_series(observations):
        if canonical_series_partition_key(ordered[0]) in incomplete:
            continue
        before, after = ordered[-2:]
        if not are_observations_compatible(before, after)[0]:
            continue
        delta = Decimal(str(after.value)) - Decimal(str(before.value))
        if delta.is_finite():
            intervals.append([before.period, after.period, format(delta, 'f')])
    return intervals
