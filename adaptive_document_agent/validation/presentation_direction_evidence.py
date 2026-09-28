"""Keep directional validation on displayed series, outside coverage references."""


def _displayed_ids(slide, charts):
    chart_ids = [*slide.chart_ids, *(cid for block in slide.visual_blocks for cid in block.chart_ids)]
    return {oid for cid in chart_ids if cid in charts for oid in charts[cid].observation_ids} | {
        oid for block in slide.visual_blocks if block.role in {"table", "kpi"}
        for oid in block.observation_ids}


def _on_displayed_series(observations, displayed):
    """Keep unrelated metrics testable; only scope a represented metric's series."""
    from adaptive_document_agent.document_model import period_sort_key
    from adaptive_document_agent.document_model.series import source_context_key

    def key(item):
        dimensions = {**item.dimensions, **item.category_dimensions}
        return ((item.metric_canonical or item.metric_original).strip().casefold(),
                item.entity, item.unit, item.unit_scale, item.currency, item.ifrs_status,
                item.effective_table_id, source_context_key(item),
                tuple(sorted({e.row_label for e in item.evidence if e.row_label})),
                tuple(sorted((key, str(value)) for key, value in dimensions.items()
                             if key not in {"table_context", "section", "column_role", "period_basis"})))
    shown = {}
    for item in observations:
        if item.id in displayed:
            shown.setdefault(key(item), []).append(item)

    def keep(item):
        peers = shown.get(key(item), [])
        periods = {peer.period for peer in peers if peer.period}
        if len(periods) < 2 or item.id in displayed or item.period in periods:
            return True
        # Intermediate observations remain necessary to check reversals. Only
        # outside periods of the identical source row can be coverage-only.
        comparable = [peer for peer in peers if (peer.period_type, peer.period_basis)
                      == (item.period_type, item.period_basis) and peer.period]
        return bool(item.period and comparable and min(period_sort_key(peer.period) for peer in comparable)
                    <= period_sort_key(item.period) <= max(period_sort_key(peer.period) for peer in comparable))
    return [item for item in observations if keep(item)]


def validate_displayed_claims(validator, slide, observations, plan, charts):
    """Read-only component views; raw references and independent bullets survive.

    A summary copy of a detailed claim follows that page's visible comparison.
    A distinct, explicitly bound summary statement retains its own period scope.
    """
    displayed = _displayed_ids(slide, charts) if slide.slide_type == "analysis" else set()
    headline = _on_displayed_series(observations, displayed) if displayed else observations
    base = slide.model_copy(update={"bullets": [], "bullet_observation_ids": []})
    issues = validator.validate_slide(base, headline)
    scoped = bool(slide.bullet_observation_ids) and len(slide.bullet_observation_ids) == len(slide.bullets)
    for index, text in enumerate(slide.bullets):
        ids = set(slide.bullet_observation_ids[index]) if scoped else {item.id for item in headline}
        selected = [item for item in observations if item.id in ids]
        if slide.slide_type in {"summary", "executive_summary"}:
            owners = [candidate for candidate in plan.slides if candidate.slide_type == "analysis"
                      and text in {candidate.title, candidate.message}]
            if len(owners) == 1:
                selected = _on_displayed_series(selected, _displayed_ids(owners[0], charts))
        part = slide.model_copy(update={"title": "", "message": "", "bullets": [text],
                                        "bullet_observation_ids": []})
        for issue in validator.validate_slide(part, selected):
            if getattr(issue, "target_component", None) == "bullet":
                issue.bullet_index = index
            issues.append(issue)
    return issues
