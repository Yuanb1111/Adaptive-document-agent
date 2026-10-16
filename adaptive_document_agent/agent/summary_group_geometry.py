"""Unpaginated copy costs and optional geometric alternatives, never semantic edits."""
from math import ceil

from adaptive_document_agent.services.presentation_brief import (
    BODY_PT, HEADING_PT, LINE_HEIGHT_FACTOR, BriefItem, _heading_height, _item_height,
)
from adaptive_document_agent.services.slide_compositor import _lines


def paragraph_geometry(item, width):
    heading = '00  ' + item.label if item.label else ''
    body = item.text if item.label else '00  ' + item.text
    heading_lines = len(_lines(heading, width, HEADING_PT)) if heading else 0
    return dict(body_wrapped_lines=len(_lines(body, width, BODY_PT)),
        heading_wrapped_lines=heading_lines,
        body_wrapped_line_height_inches=round(BODY_PT * LINE_HEIGHT_FACTOR / 72, 9),
        heading_wrapped_line_height_inches=round(HEADING_PT * LINE_HEIGHT_FACTOR / 72, 9),
        full_width_heading_height_inches=round(_heading_height(heading, width), 6) if heading else 0,
        possible_one_line_label_saving_inches=round(max(0, heading_lines-1) * HEADING_PT * LINE_HEIGHT_FACTOR / 72, 6),
        paragraph_padding_inches=.18)


def _lines_to_save(excess):
    # The actual unrounded template calculation decides fit. A tiny positive
    # excess still needs a wrap change; no epsilon grants layout acceptance.
    return max(0, ceil(max(0, excess) / (BODY_PT * LINE_HEIGHT_FACTOR / 72)))


def group_geometry(page, rows, width, height):
    """Compare the intact authored group with one slot, before pagination hides excess."""
    from adaptive_document_agent.services.compact_summary import compact_body_capacity
    capacity = compact_body_capacity(page.title, width+1.3, height)
    short_capacity = compact_body_capacity('', width+1.3, height)
    needed = sum(_item_height(BriefItem(item.label, item.text, []), width) for item in page.items)
    needed += .12 * max(0, len(page.items)-1)
    excess = max(0, needed-capacity)
    result = dict(unpaginated_full_width_load_inches=round(needed, 6),
        one_slot_capacity_inches=round(capacity, 6), one_slot_excess_inches=round(excess, 6),
        body_wrapped_lines_to_save_for_one_slot_at_current_headings=_lines_to_save(excess),
        current_body_wrapped_lines=sum(row['body_wrapped_lines'] for row in rows),
        current_heading_wrapped_lines=sum(row['heading_wrapped_lines'] for row in rows),
        paragraph_gap_total_inches=round(.12 * max(0, len(page.items)-1), 6),
        reserved_title_top_inches=round(height-1.28-capacity, 6),
        short_one_line_title_body_capacity_inches=round(short_capacity, 6),
        possible_short_title_capacity_saving_inches=round(max(0, short_capacity-capacity), 6),
        body_excess_after_short_one_line_title_inches=round(max(0, needed-short_capacity), 6),
        body_wrapped_lines_to_save_after_short_title=_lines_to_save(needed-short_capacity),
        nominal_title_wrapped_line_height_inches=round(32 / 72 * 1.22, 9),
        note='One-slot full-width comparison only; native grid is an alternative. Save wrapping or heading/padding cost by model-owned faithful synthesis, never drop selected meaning.')
    if len(page.items) > 1:
        body = ' '.join(item.text for item in page.items)
        preserving_labels = ' '.join((item.label + ': ' if index else '') + item.text
                                    for index, item in enumerate(page.items))
        def alternative(text):
            merged = BriefItem(page.items[0].label, text, [])
            cost = _item_height(merged, width)
            return dict(full_width_height_inches=round(cost, 6),
                body_wrapped_lines=len(_lines(text, width, BODY_PT)),
                saving_against_separate_paragraphs_inches=round(needed-cost, 6),
                fits_one_slot_geometry_only=cost <= capacity,
                within_single_paragraph_transport_capacity=len(text) <= 6000)
        result['optional_single_paragraph_geometry'] = dict(
            authored_item_ids=[row['item_id'] for row in rows], heading_item_id=rows[0]['item_id'],
            existing_body_concatenation=alternative(body),
            retaining_other_labels_in_body=alternative(preserving_labels),
            semantic_approval=False,
            rule='Numerical alternatives using the first existing label only, not a proposed semantic merge. The model must decide coherence, retain any meaning carried by labels, every selected assertion, fact ID and meaning reference. No copy or mapping is edited here.')
    return result


def group_slot_pressure(groups, physical_pages, maximum):
    """Expose local boundary pressure even when summed capacity appears sufficient."""
    body = [group for group in groups if group['placement'] == 'body']
    paragraphs = sum(len(group['paragraphs']) for group in body)
    load = sum(group['unpaginated_full_width_load_inches'] for group in body)
    capacity = sum(group['one_slot_capacity_inches'] for group in body)
    continuations = max(0, maximum-len(body)) if maximum is not None else None
    for group in body:
        group['base_physical_slots_for_current_group'] = 1
        group['unassigned_continuation_slots_shared_globally'] = continuations
        group['must_fit_one_slot_at_current_group_count'] = continuations == 0
    return dict(current_body_paragraphs=paragraphs,
        maximum_paragraphs_at_target=(4*maximum if maximum is not None else None),
        minimum_paragraph_count_reduction=(max(0, paragraphs-4*maximum) if maximum is not None else None),
        group_start_slots=len(body),
        group_start_slot_excess=(max(0, len(body)-maximum) if maximum is not None else None),
        unassigned_continuation_slots=continuations,
        unpaginated_full_width_load_sum_inches=round(load, 6),
        one_slot_capacity_sum_at_current_group_boundaries_inches=round(capacity, 6),
        aggregate_full_width_excess_inches=round(max(0, load-capacity), 6),
        sum_individual_group_one_slot_excess_inches=round(sum(group['one_slot_excess_inches'] for group in body), 6),
        groups_exceeding_one_full_width_slot=[group['group_id'] for group in body if group['one_slot_excess_inches'] > 0],
        diagnostic_unused_full_width_height_on_physical_slices_sum_inches=round(sum(
            max(0, page['full_width_remaining_inches']) for page in physical_pages if page['placement'] == 'body'), 6),
        unused_slice_space_is_not_pooled_capacity=True,
        semantic_approval=False,
        rule='Atomic required meanings are a review inventory, not one paragraph per meaning. The model may express multiple compatible distinct assertions in one paragraph with ALL owning references and fact IDs. Spare height on different slices/groups cannot be pooled; full-width and grid capacities cannot be added. Use only the actual slot budget, preserving labels meaning and every necessary qualifier.')
