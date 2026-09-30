"""Validate independent panels without pretending they form a complete matrix."""

import math


def validate_parallel_series(series):
    for items in series:
        if not items or len(items) > 40:
            raise ValueError("Independent series needs one to forty retained observations")
        if any(o.value is None or not math.isfinite(o.value) or not o.period or not o.evidence
               or o.validation_status != "valid" or o.anomaly_notes for o in items):
            raise ValueError("Independent series requires valid reported values and citations")
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
            raise ValueError("Independent series has conflicting values in one period/category")
