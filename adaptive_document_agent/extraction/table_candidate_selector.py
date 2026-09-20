"""Evaluation, comparison, and selection across multiple table extraction strategies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from adaptive_document_agent.document_model.metric_semantic_classifier import is_financial_statement_metric
from adaptive_document_agent.document_model.series import metric_key
from adaptive_document_agent.models.table import ExtractedTable

if TYPE_CHECKING:
    from adaptive_document_agent.models.observation import Observation


class TableCandidateSelector:
    """Evaluates candidate tables and picks/merges the set yielding the highest coherent financial series."""

    @staticmethod
    def score_table(table: ExtractedTable, extractor: object | None = None) -> tuple[float, int, int]:
        """Score a single table based on valid observations and multi-period series.

        Returns:
            (total_score, multi_period_series_count, valid_observations_count)
        """
        from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor

        obs_extractor = extractor if isinstance(extractor, ObservationExtractor) else ObservationExtractor()
        observations = obs_extractor._table_observations(table)
        if not observations:
            return 0.0, 0, 0

        valid_obs = [
            o for o in observations
            if getattr(o, "validation_status", "valid") == "valid" and o.value is not None
        ]
        if not valid_obs:
            return 0.0, 0, 0

        # Group by metric and evaluate periods
        metric_periods: dict[str, set[str]] = {}
        fin_obs_count = 0
        for o in valid_obs:
            m_key = metric_key(o)
            if o.period:
                metric_periods.setdefault(m_key, set()).add(o.period)
            metric_name = o.metric_canonical or o.metric_original
            if is_financial_statement_metric(metric_name) or (getattr(o, "unit_family", "") in ("currency", "percentage")):
                fin_obs_count += 1

        multi_period_series = sum(1 for periods in metric_periods.values() if len(periods) >= 2)
        three_plus_period_series = sum(1 for periods in metric_periods.values() if len(periods) >= 3)
        multi_period_fin_series = sum(
            1 for m_key, periods in metric_periods.items()
            if len(periods) >= 2 and (
                is_financial_statement_metric(m_key)
                or any(is_financial_statement_metric(o.metric_original) for o in valid_obs if metric_key(o) == m_key)
            )
        )

        score = (
            (multi_period_fin_series * 150.0)
            + (three_plus_period_series * 80.0)
            + (multi_period_series * 40.0)
            + (fin_obs_count * 10.0)
            + (len(valid_obs) * 2.0)
        )
        return score, multi_period_series, len(valid_obs)

    @classmethod
    def score_table_set(cls, tables: list[ExtractedTable]) -> float:
        """Aggregate score across a list of tables."""
        return sum(cls.score_table(t)[0] for t in tables)

    @classmethod
    def select_best_set(cls, candidate_sets: list[list[ExtractedTable]]) -> list[ExtractedTable]:
        """Select the candidate table set that maximizes structured financial quality."""
        non_empty_sets = [s for s in candidate_sets if s]
        if not non_empty_sets:
            return []

        best_set = max(non_empty_sets, key=cls.score_table_set)
        return best_set

    @classmethod
    def merge_or_replace_tables(
        cls,
        primary_tables: list[ExtractedTable],
        alternative_tables: list[ExtractedTable],
    ) -> list[ExtractedTable]:
        """Merge alternative tables if non-overlapping or substitute if strictly higher quality."""
        if not alternative_tables:
            return primary_tables
        if not primary_tables:
            return alternative_tables

        primary_score = cls.score_table_set(primary_tables)
        alt_score = cls.score_table_set(alternative_tables)

        if alt_score > primary_score:
            # If alternative table set is higher quality, prefer alternative
            return alternative_tables

        # Check if alternative has tables that cover distinct metrics not present in primary
        from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor

        oe = ObservationExtractor()
        primary_extractor_obs = []
        for pt in primary_tables:
            primary_extractor_obs.extend(oe._table_observations(pt))
        primary_metrics = {metric_key(o) for o in primary_extractor_obs}

        result = list(primary_tables)
        for at in alternative_tables:
            at_obs = oe._table_observations(at)
            at_metrics = {metric_key(o) for o in at_obs}
            # If this alternative table discovers metrics not present in primary, and has coherent periods
            if at_metrics and not at_metrics.issubset(primary_metrics):
                at_score, multi_period, _ = cls.score_table(at, extractor=oe)
                if multi_period >= 1 and at_score > 30.0:
                    result.append(at)
                    primary_metrics.update(at_metrics)

        return result
