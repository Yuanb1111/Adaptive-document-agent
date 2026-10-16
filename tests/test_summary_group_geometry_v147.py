"""Unpaginated line/heading costs explain near-threshold fragmentation without editing copy."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.compact_summary import expand_compact
from adaptive_document_agent.agent.summary_layout_feedback import layout_feedback
from adaptive_document_agent.agent.summary_layout_patch import layout_patch_messages
from adaptive_document_agent.agent.summary_theme_layout import pack_theme_pages
from adaptive_document_agent.services.presentation_brief import BriefItem, _item_height
from tests.test_summary_compression_v145 import compression_fixture


def near_threshold(title='Reported service and activity measures'):
    _, review, catalog, _, draft = compression_fixture()
    draft.pages[0].title = title
    draft.pages[0].items = draft.pages[0].items[:2]
    for item, lines in zip(draft.pages[0].items, (6, 5)):
        item.label = 'Supported scope'
        item.text = '\n'.join(['Supported service.'] * lines)
        item.meaning_refs[0].summary_quote = item.text
    pages = pack_theme_pages(expand_compact(draft, catalog, review))
    return review, catalog, draft, pages


def test_eleven_wrapped_body_lines_expose_the_near_one_slot_excess_before_pagination():
    review, catalog, draft, pages = near_threshold()
    before = deepcopy(draft)
    feedback = layout_feedback(draft, pages, review, catalog)
    group = feedback['groups'][0]
    assert len(pages) == 2 and group['current_physical_slides'] == 2
    assert group['title_lines'] == 1 and group['continuation_title_lines'] == 2
    assert group['current_body_wrapped_lines'] == 11
    assert [row['body_wrapped_lines'] for row in group['paragraphs']] == [6, 5]
    assert all(row['heading_wrapped_lines'] == 1 for row in group['paragraphs'])
    assert group['unpaginated_full_width_load_inches'] == pytest.approx(4.240556, abs=.000001)
    assert group['one_slot_capacity_inches'] == pytest.approx(4.182361, abs=.000001)
    assert group['one_slot_excess_inches'] == pytest.approx(.058194, abs=.000001)
    assert group['body_wrapped_lines_to_save_for_one_slot_at_current_headings'] == 1
    assert group['paragraphs'][0]['body_wrapped_line_height_inches'] == pytest.approx(16*1.25/72)
    assert group['paragraphs'][0]['heading_wrapped_line_height_inches'] == pytest.approx(18*1.25/72)
    assert group['must_fit_one_slot_at_current_group_count'] is True
    pressure = feedback['group_slot_pressure']
    assert pressure['groups_exceeding_one_full_width_slot'] == ['g0']
    assert pressure['diagnostic_unused_full_width_height_on_physical_slices_sum_inches'] > 0
    assert pressure['unused_slice_space_is_not_pooled_capacity'] is True
    assert draft == before and feedback['semantic_approval'] is False


def test_title_reservation_cost_and_short_title_alternative_are_distinct_from_body_savings():
    review, catalog, draft, pages = near_threshold(
        'Supported capabilities with comprehensive operating context')
    group = layout_feedback(draft, pages, review, catalog)['groups'][0]
    assert group['title_lines'] == 2 and group['continuation_title_lines'] == 3
    assert group['one_slot_excess_inches'] == pytest.approx(.600417, abs=.000001)
    assert group['possible_short_title_capacity_saving_inches'] == pytest.approx(.716667, abs=.000001)
    assert group['body_wrapped_lines_to_save_for_one_slot_at_current_headings'] == 3
    assert group['body_excess_after_short_one_line_title_inches'] == 0
    assert group['body_wrapped_lines_to_save_after_short_title'] == 0
    assert group['nominal_title_wrapped_line_height_inches'] == pytest.approx(32/72*1.22)


def test_optional_merge_metrics_retain_item_addresses_without_authoring_or_approving_a_merge():
    review, catalog, draft, pages = near_threshold()
    before = deepcopy(draft)
    group = layout_feedback(draft, pages, review, catalog)['groups'][0]
    choice = group['optional_single_paragraph_geometry']
    assert choice['authored_item_ids'] == ['g0_i0', 'g0_i1'] and choice['heading_item_id'] == 'g0_i0'
    expected = _item_height(BriefItem(draft.pages[0].items[0].label,
        ' '.join(item.text for item in draft.pages[0].items), []), group['full_width_inches'])
    assert choice['existing_body_concatenation']['full_width_height_inches'] == pytest.approx(expected, abs=.000001)
    assert choice['existing_body_concatenation']['fits_one_slot_geometry_only'] is True
    assert choice['existing_body_concatenation']['saving_against_separate_paragraphs_inches'] > .5
    assert choice['retaining_other_labels_in_body']['fits_one_slot_geometry_only'] is True
    assert choice['semantic_approval'] is False and 'meaning carried by labels' in choice['rule']
    assert not any(item.text in json.dumps(choice) for item in draft.pages[0].items)
    assert draft == before


def test_every_group_and_paragraph_is_counted_even_before_physical_pagination():
    _, review, catalog, draft, _ = compression_fixture()
    review.max_intro_slides = 2
    draft.pages[0].items *= 10
    before = deepcopy(draft)
    feedback = layout_feedback(draft, None, review, catalog)
    pressure = feedback['group_slot_pressure']
    assert pressure['current_body_paragraphs'] == 12
    assert pressure['maximum_paragraphs_at_target'] == 8
    assert pressure['minimum_paragraph_count_reduction'] == 4
    assert pressure['group_start_slots'] == 3 and pressure['group_start_slot_excess'] == 1
    assert pressure['unassigned_continuation_slots'] == 0
    assert [group['group_id'] for group in feedback['groups']] == ['g0', 'g1', 'g2']
    assert [len(group['paragraphs']) for group in feedback['groups']] == [10, 1, 1]
    assert all('body_wrapped_lines' in row for group in feedback['groups'] for row in group['paragraphs'])
    assert sum(group['unpaginated_full_width_load_inches'] for group in feedback['groups']) == pytest.approx(
        pressure['unpaginated_full_width_load_sum_inches'], abs=.000002)
    assert all(group['current_physical_slides'] is None for group in feedback['groups'])
    assert 'multiple compatible distinct assertions' in pressure['rule']
    assert draft == before


def test_allocation_feedback_distinguishes_local_excess_from_a_global_sum():
    review, catalog, draft, pages = near_threshold()
    # A second short group has spare space, but cannot donate it across headings.
    other = draft.pages[0].model_copy(deep=True)
    other.title = 'Other context'
    other.items = other.items[:1]
    other.items[0].text = 'Supported service.'
    other.items[0].meaning_refs[0].summary_quote = other.items[0].text
    draft.pages.append(other)
    review.max_intro_slides = 2
    feedback = layout_feedback(draft, None, review, catalog)
    pressure = feedback['group_slot_pressure']
    assert pressure['aggregate_full_width_excess_inches'] == 0
    assert pressure['sum_individual_group_one_slot_excess_inches'] > 0
    assert pressure['groups_exceeding_one_full_width_slot'] == ['g0']
    assert all(group['must_fit_one_slot_at_current_group_count'] for group in feedback['groups'])


def test_model_wire_exposes_geometry_without_repeating_body_text_or_losing_owned_inventory():
    review, catalog, draft, pages = near_threshold()
    feedback = layout_feedback(draft, pages, review, catalog)
    record = dict(layout_feedback=feedback, errors=['Measured group excess.'], compression_round=1,
                  compression_round_limit=2)
    messages = layout_patch_messages(draft, catalog, record, 'Use the actual slot budget.', audience_selected=True)
    value = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert value['layout_feedback']['version'] == 'physical-meaning-layout-v2'
    assert len(value['layout_feedback']['meaning_inventory']) == 3
    assert value['current_pages'][0]['items'][0]['text'] == draft.pages[0].items[0].text
    assert value['layout_feedback']['groups'][0]['optional_single_paragraph_geometry']['authored_item_ids'] == ['g0_i0', 'g0_i1']
    assert 'atomic meaning inventory is not paragraph count' in messages[0]['content']
    assert 'preserve any meaning carried by the original labels' in messages[0]['content']
    assert 'stranded, not pooled' in messages[0]['content']
