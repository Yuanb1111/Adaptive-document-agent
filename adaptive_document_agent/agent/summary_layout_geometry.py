"""Expose native physical capacity as writing feedback, never as semantic approval."""
from adaptive_document_agent.services.compact_summary import compact_body_capacity, _template_dimensions
from adaptive_document_agent.services.pptx_export import _resolve_template_path


def physical_allocation(max_slides, *, logical_groups=0, physical_slides=None):
    """A group always starts a slide; continuation slots share the same hard cap."""
    path = _resolve_template_path()
    width, height = _template_dimensions(str(path), path.stat().st_mtime_ns)
    return dict(target_physical_slides=max_slides, logical_body_groups=logical_groups,
        current_physical_slides=physical_slides,
        continuation_slots_after_group_starts=(max(0, max_slides-logical_groups)
                                               if max_slides is not None else None),
        current_continuation_slides=(max(0, physical_slides-logical_groups)
                                    if physical_slides is not None else None),
        one_line_title_body_capacity_inches=round(compact_body_capacity('', width, height), 6),
        full_width_inches=round(width-1.3, 6), paragraph_gap_inches=.12,
        max_items_per_physical_slide=4, body_font_pt=16, paragraph_heading_font_pt=18,
        title_font_pt=32, semantic_approval=False,
        rule='Every logical group starts a physical slide. Reassign related meanings across groups '
             'if needed; a group with no continuation slot must fit one physical slide. '
             'Full-width and native grid geometry are alternatives, not additive capacities.')


def physical_page_loads(pages, draft, catalog):
    """Report both native layout alternatives; negative space is not spare capacity."""
    from adaptive_document_agent.services.presentation_brief import (
        BriefItem, _item_height, _heading_height, _copy_height)
    from adaptive_document_agent.services.slide_compositor import _lines

    path = _resolve_template_path()
    width, height = _template_dimensions(str(path), path.stat().st_mtime_ns)
    full_width = width-1.3
    origins = []
    for g, group in enumerate(draft.pages):
        for i, item in enumerate(group.items):
            refs = {(catalog[fid][0].id, catalog[fid][1]) for fid in item.fact_ids if fid in catalog}
            origins.append((f'g{g}_i{i}', group.title, item, refs))
    result = []
    for index, page in enumerate(pages or []):
        items = [BriefItem(item.label, item.text, []) for item in page.items]
        capacity = compact_body_capacity(page.title, width, height)
        needed = sum(_item_height(item, full_width) for item in items) + .12*max(0, len(items)-1)
        rows = []
        for item, measured in zip(page.items, items):
            refs = {(ref.part_id, ref.fact_index) for ref in item.source_refs}
            matches = [identifier for identifier, title, original, owners in origins
                       if title == page.title and original.label == item.label
                       and item.text in original.text and owners == refs]
            rows.append(dict(authored_item_ids=matches,
                full_width_height_inches=round(_item_height(measured, full_width), 6)))
        grid = None
        if len(items) in {3, 4}:
            columns, row_count = (3, 1) if len(items) == 3 else (2, 2)
            top = max(1.45, .27+len(_lines(page.title, min(8.91, width-.75), 32))*(32/72*1.22)+.27)
            cell_width = (full_width-.34*(columns-1))/columns
            cell_height = (height-1.20-top-.18*(row_count-1))/row_count
            cells = [dict(heading_lines=len(_lines(item.title, cell_width, 18)),
                remaining_height_inches=round(cell_height - (_heading_height(item.title, cell_width)
                    + .06 + _copy_height(item.text, cell_width, 16) + .08), 6)) for item in items]
            grid = dict(columns=columns, rows=row_count, cell_width_inches=round(cell_width, 6),
                cell_height_inches=round(cell_height, 6), cells=cells,
                fits=all(cell['heading_lines'] <= 2 and cell['remaining_height_inches'] >= 0
                         for cell in cells))
        result.append(dict(physical_slide=index+1, title=page.title, placement=page.placement,
            paragraphs=rows, full_width_capacity_inches=round(capacity, 6),
            full_width_needed_inches=round(needed, 6),
            full_width_remaining_inches=round(capacity-needed, 6),
            full_width_fits=needed <= capacity, native_grid=grid))
    return result
