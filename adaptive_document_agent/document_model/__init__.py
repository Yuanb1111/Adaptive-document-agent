"""Global observation model and indexes."""

from .builder import DocumentModelBuilder
from .index import DocumentIndex
from .chartability import ChartabilityResult, score_chartability
from .series import (
    best_period_series,
    canonical_series_partition_key,
    conflicting_groups,
    context_key,
    display_metric_name,
    group_comparable_series,
    is_generic_metric_label,
    is_meaningful_metric,
    is_meaningful_metric_name,
    metric_identity_key,
    metric_key,
    metric_label,
    paired_observations,
    period_sort_key,
    presentation_sign_variant_groups,
    reconcile_observations,
)

from .period_semantic_validator import (
    are_periods_comparable,
    classify_period,
    extract_period_basis,
    format_canonical_period,
    format_observation_period,
    format_period_label,
)

__all__ = [
    "ChartabilityResult",
    "DocumentIndex",
    "DocumentModelBuilder",
    "are_periods_comparable",
    "best_period_series",
    "canonical_series_partition_key",
    "classify_period",
    "conflicting_groups",
    "context_key",
    "display_metric_name",
    "extract_period_basis",
    "format_canonical_period",
    "format_observation_period",
    "format_period_label",
    "group_comparable_series",
    "is_generic_metric_label",
    "is_meaningful_metric",
    "is_meaningful_metric_name",
    "metric_identity_key",
    "metric_key",
    "metric_label",
    "paired_observations",
    "period_sort_key",
    "presentation_sign_variant_groups",
    "reconcile_observations",
    "score_chartability",
]
