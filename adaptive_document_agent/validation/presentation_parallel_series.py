"""Validate independent panels without pretending they form a complete matrix."""

import math


def validate_parallel_series(series):
    for items in series:
        if not items or len(items) > 40:
            raise ValueError("Independent series needs one to forty retained observations")
        for o in items:
            missing = []
            if o.value is None or not math.isfinite(o.value): missing.append('finite reported value')
            if not o.period: missing.append('source-bound period')
            if not o.evidence: missing.append('source citation')
            if o.validation_status != 'valid' or o.anomaly_notes: missing.append('validated unambiguous evidence')
            if missing:
                raise ValueError('Independent series requires valid reported values and citations; '
                                 + o.id + ' lacks ' + ', '.join(missing))
        units = {(o.unit_family or o.unit, o.currency, o.unit_scale, o.raw_unit) for o in items}
        if len(units) != 1:
            raise ValueError("Independent series mixes units or currencies")
        from adaptive_document_agent.document_model.period_semantic_validator import extract_period_basis
        bases = {extract_period_basis(o.period) for o in items}
        if len(bases) > 1:
            raise ValueError("Independent series mixes incompatible period bases")
        cells = {}
        for o in items:
            key = (o.period, o.entity, tuple(sorted(o.category_dimensions.items())))
            cells.setdefault(key, set()).add(o.value)
        if any(len(values) > 1 for values in cells.values()):
            # A complete category composition is a panel, not one time series.
            # Extractors may preserve categories in literal source row labels
            # rather than category_dimensions. Reuse the full composition gate;
            # never reinterpret conflicting scalar cells by their metric names.
            from adaptive_document_agent.document_model import DocumentIndex
            from adaptive_document_agent.services.composition_candidates import presentation_compositions
            ids = {o.id for o in items}
            if any(ids == set([*chart.observation_ids, *chart.total_observation_ids])
                   for chart in presentation_compositions(DocumentIndex(items))):
                continue
            raise ValueError("Independent series has conflicting values in one period/category")
