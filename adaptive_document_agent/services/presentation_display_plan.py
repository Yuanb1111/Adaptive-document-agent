"""Lossless physical-page choices for already selected presentation evidence.

The authored plan and raw observations stay untouched. Only complete, exact
corroborating series can share a display page; conflicting values never match.
"""

from math import ceil

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.document_model.series import is_generic_metric_label


def balanced_groups(items, maximum=3):
    """Keep order and avoid a one-panel tail when a balanced split is possible."""
    pages = max(1, ceil(len(items) / maximum))
    size, extra = divmod(len(items), pages)
    groups, start = [], 0
    for number in range(pages):
        end = start + size + (number < extra)
        if end > start:
            groups.append(items[start:end])
        start = end
    return groups


def _fact_signature(observation):
    if (observation.value is None or not observation.period or not observation.evidence
            or observation.validation_status != "valid" or observation.anomaly_notes
            or is_generic_metric_label(observation.metric_original)):
        return None
    # Strip only extraction location metadata. Parent/category/row scope,
    # reporting basis, units and source precision are still part of identity.
    dimensions = tuple(sorted((key, str(value)) for key, value in
        {**observation.dimensions, **observation.category_dimensions}.items()
        if key not in {"table_context", "section"}))
    return (display_metric_name(observation).casefold(), observation.metric_original.casefold(),
            observation.parent_section, dimensions, observation.entity,
            observation.unit, observation.unit_family, observation.currency,
            observation.raw_value, observation.raw_unit, observation.unit_scale,
            observation.period, observation.period_basis, observation.period_type,
            observation.period_start, observation.period_end, observation.as_of_date,
            observation.audited_status, observation.ifrs_status, observation.fact_type,
            observation.value)


def _series_signature(items):
    signatures = [_fact_signature(item) for item in items]
    if len(signatures) < 2 or any(value is None for value in signatures):
        return None
    return frozenset(signatures)


def display_slides(plan, charts, index):
    """Omit corroborating table pages, retaining their plan and facts in notes.

    Restrict sharing to the same authored theme. A table with independent copy,
    a subset of periods, another unit or an adjusted measure remains visible.
    """
    output = []
    owners = {}
    for source in plan.slides:
        if source.slide_type != "analysis" or not source.theme_id:
            output.append(source)
            continue
        chart_ids = list(dict.fromkeys([*source.chart_ids,
            *(cid for block in source.visual_blocks for cid in block.chart_ids)]))
        pure_table = (not chart_ids and not source.bullets and not source.insight_ids
                      and all(block.role == "table" and not block.insight_ids
                              for block in source.visual_blocks))
        ids = list(dict.fromkeys([*source.observation_ids,
            *(oid for block in source.visual_blocks for oid in block.observation_ids)]))
        values = [index.get(oid) for oid in ids if index.get(oid)]
        signature = _series_signature(values) if pure_table else None
        owner = owners.get((source.theme_id, signature)) if signature else None
        if owner is not None and source.message in {owner.message, owner.analytical_question, ""}:
            position = output.index(owner)
            updated = owner.model_copy(update={
                "source_pages": sorted(set(owner.source_pages) | set(source.source_pages)),
            })
            # Private metadata is export-only; all records also remain in the
            # original plan, appendix and downloaded analysis data.
            previous = getattr(owner, "_corroborating_pages", [])
            object.__setattr__(updated, "_corroborating_pages", [*previous, source])
            output[position] = updated
            for key, value in list(owners.items()):
                if value is owner:
                    owners[key] = updated
            continue
        output.append(source)
        for cid in chart_ids:
            chart = charts.get(cid)
            if chart is None:
                continue
            signature = _series_signature([index.get(oid) for oid in chart.observation_ids if index.get(oid)])
            if signature:
                owners.setdefault((source.theme_id, signature), source)
    return _balance_existing_chart_pages(output, charts, index)


def _balance_existing_chart_pages(slides, charts, index):
    """Apply the same capacity rule when replaying an older cached plan."""
    output, position = [], 0
    while position < len(slides):
        source = slides[position]
        group = [source]
        eligible = lambda item: (item.slide_type == "analysis" and item.theme_id
            and item.chart_ids and not item.visual_blocks and not item.bullets
            and not item.observation_ids and not item.insight_ids
            and not getattr(item, "_corroborating_pages", []))
        if eligible(source):
            while position + len(group) < len(slides):
                following = slides[position + len(group)]
                if (not eligible(following) or following.theme_id != source.theme_id
                        or following.message != source.message):
                    break
                group.append(following)
        ids = [cid for page in group for cid in page.chart_ids]
        batches = balanced_groups(ids) if len(group) > 1 and len(set(ids)) == len(ids) else []
        if batches and len(batches) == len(group):
            for page, batch in zip(group, batches):
                pages = sorted({e.page for cid in batch if cid in charts
                    for oid in [*charts[cid].observation_ids, *charts[cid].total_observation_ids]
                    if index.get(oid) for e in index.get(oid).evidence})
                output.append(page.model_copy(update={"chart_ids": batch, "source_pages": pages,
                    "layout": "three_up" if len(batch) == 3 else "two_up" if len(batch) == 2 else "single"}))
        else:
            output.extend(group)
        position += len(group)
    return output


def corroboration_record(slide, index):
    """Retain every corroborating source record, without changing originals."""
    copies = getattr(slide, "_corroborating_pages", [])
    if not copies:
        return None
    ids = list(dict.fromkeys(oid for source in copies for oid in [*source.observation_ids,
        *(oid for block in source.visual_blocks for oid in block.observation_ids)]))
    return {
        "slides": [source.model_dump(mode="json") for source in copies],
        "observations": [index.get(oid).model_dump(mode="json") for oid in ids if index.get(oid)],
    }


def corroboration_notes(slide, index):
    """Readable export-only audit for callers that already have prose notes."""
    import json
    record = corroboration_record(slide, index)
    return ("Corroborating source pages (same complete reported series):\n"
            + json.dumps(record, ensure_ascii=False)) if record else ""
