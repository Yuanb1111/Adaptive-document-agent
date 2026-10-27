"""Arithmetic options cannot choose meaning, invent savings or relax a page cap."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.presentation_budget_options import whole_topic_cost_options


def costs():
    sizes = [3, 1, 3, 2, 3, 2]
    groups = []
    first = 9
    for i, size in enumerate(sizes):
        groups.append(dict(topic_id=f't{i}', physical_slide_numbers=list(range(first, first + size))))
        first += size
    counts = dict(analysis=14, topic_pages=[dict(topic_id=f't{i}', physical_slides=size)
                  for i, size in enumerate(sizes)], native_groups=groups)
    allocation = dict(effective_analysis_capacity=10, constraints=[
        dict(slide_scope='body', current_non_analysis_slides=9, maximum_slides=20),
        dict(slide_scope='all', current_non_analysis_slides=10, maximum_slides=21)])
    return counts, allocation


def test_omitting_two_of_fourteen_pages_never_claims_to_fit_ten():
    counts, allocation = costs()
    before = deepcopy((counts, allocation))
    result = whole_topic_cost_options(counts, allocation)
    assert result['status'] == 'available'
    choices = {tuple(option['retained_topic_ids']): option for option in result['options']}
    assert ('t0', 't1', 't2', 't3', 't4') not in choices  # 12, not 10.
    fitting = choices[('t0', 't1', 't2', 't4')]
    assert fitting['measured_analysis_slides'] == 10
    assert fitting['omitted_topic_ids'] == ['t3', 't5']
    assert [cap['projected_slides'] for cap in fitting['report_scopes_with_current_other_pages']] == [19, 20]
    for option in result['options']:
        assert option['measured_analysis_slides'] <= 10
        assert all(cap['projected_slides'] <= cap['maximum_slides']
                   for cap in option['report_scopes_with_current_other_pages'])
        assert set(option['retained_topic_ids']).isdisjoint(option['omitted_topic_ids'])
        assert set(option['retained_topic_ids'] + option['omitted_topic_ids']) == {f't{i}' for i in range(6)}
    assert (counts, allocation) == before


@pytest.mark.parametrize('defect', ['shared', 'missing', 'unknown_owner', 'wrong_cost', 'wrong_total', 'duplicate_topic'])
def test_non_additive_or_incomplete_native_mapping_has_no_invented_subset_cost(defect):
    counts, allocation = costs()
    if defect == 'shared':
        counts['native_groups'][1]['physical_slide_numbers'] = [9]
    elif defect == 'missing':
        counts['native_groups'].pop()
    elif defect == 'unknown_owner':
        counts['native_groups'][0]['topic_id'] = 'unknown'
    elif defect == 'wrong_cost':
        counts['topic_pages'][0]['physical_slides'] = 2
    elif defect == 'wrong_total':
        counts['analysis'] = 13
    else:
        counts['topic_pages'][1]['topic_id'] = 't0'
    result = whole_topic_cost_options(counts, allocation)
    assert result['status'] == 'unavailable' and not result['options']


def test_no_room_cannot_create_a_zero_topic_or_automatically_accepted_plan():
    counts, allocation = costs()
    allocation['effective_analysis_capacity'] = 0
    result = whole_topic_cost_options(counts, allocation)
    assert result['status'] == 'available' and not result['options']


def test_each_report_scope_is_checked_even_if_supplied_analysis_capacity_is_looser():
    counts, allocation = costs()
    allocation['constraints'][1]['maximum_slides'] = 12
    result = whole_topic_cost_options(counts, allocation)
    assert result['options']
    assert all(option['measured_analysis_slides'] <= 2 for option in result['options'])


def test_eight_topic_limit_bounds_enumeration_without_silently_dropping_topics():
    counts = dict(analysis=8,
        topic_pages=[dict(topic_id=str(i), physical_slides=1) for i in range(8)],
        native_groups=[dict(topic_id=str(i), physical_slide_numbers=[i+1]) for i in range(8)])
    allocation = dict(effective_analysis_capacity=8, constraints=[])
    assert len(whole_topic_cost_options(counts, allocation)['options']) == 255
    counts['topic_pages'].append(dict(topic_id='8', physical_slides=1))
    result = whole_topic_cost_options(counts, allocation)
    assert result['status'] == 'unavailable' and not result['options']
