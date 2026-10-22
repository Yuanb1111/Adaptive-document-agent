"""Measure alternate native geometry before sacrificing selected topic coverage."""

import re


def table_row_cut(heights, capacity, group_sizes, *, narrow=False):
    """Keep fitting period groups intact and balance a two-page table.

    Heights exclude the repeated header. Row order never changes. A narrow
    support slot can defer a small group to the wider continuation; an oversized
    group on a full page may still split so pagination always makes progress.
    """
    prefix = [0.0]
    for height in heights:
        prefix.append(prefix[-1] + height)
    fitting = [i for i in range(len(prefix)) if prefix[i] <= capacity + 1e-6]
    cut = max(fitting, default=0)
    if cut == len(heights):
        return cut
    protected, start = set(), 0
    for size in group_sizes:
        end = start + size
        if size <= 6 and (narrow or prefix[end] - prefix[start] <= capacity + 1e-6):
            protected.update(range(start + 1, end))
        start = end
    allowed = [i for i in fitting if i not in protected]
    cut = max(allowed, default=0)
    if not narrow:
        # Prefer balanced complete groups when all remaining rows fit on one
        # more page. Do not create extra pages merely to equalize whitespace.
        balanced = [i for i in allowed if i > 0 and prefix[-1] - prefix[i] <= capacity + 1e-6]
        if balanced:
            cut = min(balanced, key=lambda i: (abs(prefix[-1] - 2 * prefix[i]), -i))
    return cut


def unplotted_table_ids(ids, plotted, index):
    """Remove only complete exact series already visible in native charts."""
    from .presentation_evidence import evidence_groups
    groups = evidence_groups([index.get(oid) for oid in ids if index.get(oid)])
    repeated = {o.id for group in groups if {o.id for o in group} <= plotted for o in group}
    return [oid for oid in ids if oid not in repeated]


def matching_duration_ranges(groups):
    """A shared duration label must denote the same retained source interval.

    Labels alone remain usable when every record lacks explicit endpoints.
    Once one record gives an interval, another record sharing that column must
    retain both identical endpoints; partial/missing bounds are not inferred.
    """
    from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period

    intervals = {}
    for group in groups:
        for item in group:
            label = format_observation_period(item).rstrip('*')
            if re.fullmatch(r'\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}', label):
                continue
            start, end = item.period_start or None, item.period_end or None
            if (start is None) != (end is None):
                return False
            intervals.setdefault(label, set()).add((start, end))
    return all(len(bounds) == 1 for bounds in intervals.values())


def sparse_period_columns(groups):
    """Share resolved columns without inventing absent duration/date records."""
    from adaptive_document_agent.document_model import period_sort_key
    from adaptive_document_agent.document_model.period_semantic_validator import (
        extract_period_basis, format_observation_period,
    )
    items = [item for group in groups for item in group]
    periods = [tuple(format_observation_period(item) for item in group) for group in groups]
    exact_date = re.compile(r'^\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}\*?$')
    # Use the source-backed display date as well: raw ISO dates and as_of_date
    # metadata are precise even though extract_period_basis returns generic.
    bases = {'point_in_time' if exact_date.fullmatch(format_observation_period(item))
             else extract_period_basis(item.period) for item in items}
    qualifiers = {}
    for group in periods:
        for label in group:
            qualifiers.setdefault(label.rstrip('*'), set()).add(label)
    if (len(bases) != 1 or 'generic' in bases or not periods
            or not matching_duration_ranges(groups)
            or any(not value for group in periods for value in group)
            or any(len(variants) > 1 for variants in qualifiers.values())
            or any(item.period_basis not in {'', 'generic', *bases} for item in items)
            or any(len({value.rstrip('*') for value in group}) != len(group) for group in periods)):
        return ()
    # Point-date groups retain the established two-date overlap requirement.
    # A one-period duration disclosure can accompany comparable duration
    # series, with an explicit blank rather than a fabricated earlier value.
    minimum_overlap = 2 if bases == {'point_in_time'} else 1
    if len(set.intersection(*(set(group) for group in periods))) < minimum_overlap:
        return ()
    columns = tuple(dict.fromkeys(format_observation_period(item)
        for item in sorted(items, key=lambda item: period_sort_key(item.as_of_date or item.period))))
    return columns if 2 <= len(columns) <= 6 else ()


def _remove_pages(presentation, slides):
    ids = {slide.slide_id for slide in slides}
    for identifier in list(presentation.slides._sldIdLst):
        if identifier.id in ids:
            presentation.part.drop_rel(identifier.rId)
            presentation.slides._sldIdLst.remove(identifier)


def compact_support_pages(presentation, plan, charts, result, index, rendered):
    """Prefer grouped charts and a complete table over fragmented side panels.

    Both candidates use the normal compositor and its evidence/geometry checks.
    Fewer pages, or an unsplit table at the same page count, wins; no claim or
    selected source row is dropped. Budget measurement uses the same path.
    """
    table_blocks = [block for block in plan.visual_blocks if block.role == 'table']
    if (len(rendered) <= 1 or len(charts) < 2 or not table_blocks
            or any(block.role == 'kpi' for block in plan.visual_blocks)):
        return rendered
    from .slide_compositor import _render_composed_slide, _ChartCapacityError, validate_composed_geometry
    from .qa_reporter import CriticalQAError

    table_ids = list(dict.fromkeys(oid for block in table_blocks for oid in block.observation_ids))
    table_ids = unplotted_table_ids(table_ids, {oid for c in charts for oid in c.observation_ids}, index)
    if not table_ids:
        return rendered
    chart_plan = plan.model_copy(update={
        'observation_ids': list(dict.fromkeys([*plan.observation_ids, *table_ids])),
        'visual_blocks': [block for block in plan.visual_blocks if block.role != 'table'],
        'insight_ids': list(dict.fromkeys([*plan.insight_ids,
            *(iid for block in table_blocks for iid in block.insight_ids)])),
        'layout': 'three_up' if len(charts) == 3 else 'two_up',
    })
    # Keep all authored copy on the charts. The adjoining table carries the
    # same topic heading and only the explicitly selected supporting records.
    table_plan = plan.model_copy(update={
        'chart_ids': [], 'observation_ids': table_ids,
        'visual_blocks': [block.model_copy(update={'chart_ids': [], 'insight_ids': [],
            'observation_ids': [oid for oid in block.observation_ids if oid in table_ids]}) for block in table_blocks],
        'layout': 'data_overview', 'message': '', 'bullets': [],
        'bullet_observation_ids': [], 'insight_ids': [],
    })
    start = len(presentation.slides)
    try:
        chart_pages = _render_composed_slide(presentation, chart_plan, charts, result, index)
        table_pages = _render_composed_slide(presentation, table_plan, [], result, index)
        alternative = chart_pages + table_pages
        validate_composed_geometry(presentation)
    except (_ChartCapacityError, CriticalQAError):
        _remove_pages(presentation, list(presentation.slides)[start:])
        return rendered
    table_count = lambda pages: sum(shape.has_table for page in pages for shape in page.shapes)
    if (len(alternative) > len(rendered)
            or len(alternative) == len(rendered) and table_count(alternative) >= table_count(rendered)):
        _remove_pages(presentation, alternative)
        return rendered
    _remove_pages(presentation, rendered)
    return alternative
