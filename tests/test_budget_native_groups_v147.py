"""Measured renderer provenance informs model priorities without predicting savings."""
from types import SimpleNamespace as S

from adaptive_document_agent.agent.presentation_budget_geometry import measured_native_groups


def fixture():
    result = S(
        presentation_topics=S(topics=[S(id='topic-a', series_ids=['a', 'b', 'c', 'missing']),
                                      S(id='topic-b', series_ids=['d'])]),
        presentation_plan=S(slides=[
            S(id='charts', layout='two_up', visual_blocks=[]),
            S(id='matrix', layout='data_overview', visual_blocks=[S(role='matrix')]),
            S(id='other', layout='single', visual_blocks=[])]),
        charts=[S(id='chart-a', observation_ids=['a1', 'a2'], total_observation_ids=[]),
                S(id='chart-b', observation_ids=['b1'], total_observation_ids=[])],
        presentation_export_trace=[
            dict(planned_slide_id='charts', topic_id='topic-a', slide_numbers=[5, 6],
                 chart_ids=['chart-a', 'chart-b'], observation_ids=[]),
            dict(planned_slide_id='matrix', topic_id='topic-a', slide_numbers=[7],
                 chart_ids=[], observation_ids=['c1', 'c2']),
            dict(planned_slide_id='other', topic_id='topic-b', slide_numbers=[7],
                 chart_ids=[], observation_ids=['d1'])])
    lookup = {sid: [S(id=oid) for oid in ids] for sid, ids in
              dict(a=['a1', 'a2'], b=['b1', 'b2'], c=['c1', 'c2'], d=['d1'], foreign=['a1']).items()}
    return result, lookup


def test_chart_membership_is_explicit_and_partial_scope_is_not_called_complete():
    result, lookup = fixture()
    group = measured_native_groups(result, lookup)[0]
    assert group['physical_slide_numbers'] == [5, 6] and group['measured_physical_slides'] == 2
    assert group['owning_series_ids'] == ['a', 'b']
    assert group['series_input_membership'] == [
        dict(series_id='a', input_membership='complete', matched_observation_count=2, series_observation_count=2),
        dict(series_id='b', input_membership='partial', matched_observation_count=1, series_observation_count=2)]
    assert group['topic_series_outside_this_group'] == ['c']
    assert group['unknown_topic_series_ids'] == ['missing']
    assert 'foreign' not in group['owning_series_ids']
    assert 'not claim-by-claim display proof or predicted subset cost' in group['mapping_basis']


def test_one_page_matrix_keeps_its_whole_input_group_without_linear_series_costs():
    result, lookup = fixture()
    group = measured_native_groups(result, lookup)[1]
    assert group['layout'] == 'data_overview' and group['visual_roles'] == ['matrix']
    assert group['owning_series_ids'] == ['c'] and group['measured_physical_slides'] == 1
    assert 'savings' not in group and 'cost_per_series' not in group
    assert group['co_located_groups'] == [dict(physical_slide=7, planned_slide_ids=['matrix', 'other'])]


def test_unknown_plan_charts_and_unmatched_source_remain_explicit_not_invented():
    result, lookup = fixture()
    result.presentation_export_trace = [dict(planned_slide_id='unknown-plan', topic_id='topic-a',
        slide_numbers=[9, 9, True, -1], chart_ids=['unknown-chart'], observation_ids=['unowned'])]
    group, = measured_native_groups(result, lookup)
    assert group['physical_slide_numbers'] == [9]
    assert group['planned_slide_found'] is False and group['layout'] is None
    assert group['unknown_chart_ids'] == ['unknown-chart'] and group['owning_series_ids'] == []
    assert group['topic_series_outside_this_group'] == ['a', 'b', 'c']
    assert group['unknown_topic_series_ids'] == ['missing']


def test_revised_subset_uses_only_its_current_topic_scope_without_source_remapping():
    result, lookup = fixture()
    result.presentation_topics.topics[0].series_ids = ['b']
    groups = measured_native_groups(result, lookup)
    assert groups[0]['owning_series_ids'] == ['b']
    assert groups[0]['series_input_membership'][0]['input_membership'] == 'partial'
    assert groups[1]['owning_series_ids'] == []
    assert result.presentation_export_trace[0]['observation_ids'] == []
    assert lookup['b'][1].id == 'b2'


def test_missing_trace_never_creates_a_topic_cost_or_semantic_acceptance():
    result, lookup = fixture()
    result.presentation_export_trace = []
    assert measured_native_groups(result, lookup) == []
