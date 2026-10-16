"""Expose measured renderer groups without predicting semantic subset costs."""


def _ids(value):
    return {item for item in value if isinstance(item, str)} if isinstance(value, (list, tuple)) else set()


def measured_native_groups(result, lookup):
    """Map existing native groups to their own selected source series only.

    A trace records renderer inputs, including all inputs to a continuation. It
    cannot prove which claim is visible on each page or how a new subset fits.
    """
    topics = {topic.id: topic for topic in result.presentation_topics.topics}
    plans = {slide.id: slide for slide in result.presentation_plan.slides}
    charts = {chart.id: chart for chart in result.charts}
    traces = [trace for trace in result.presentation_export_trace
              if trace.get('topic_id') in topics]
    page_owners = {}
    for trace in traces:
        for number in trace.get('slide_numbers', []):
            if isinstance(number, int) and not isinstance(number, bool) and number > 0:
                page_owners.setdefault(number, set()).add(trace.get('planned_slide_id'))
    groups = []
    for trace in traces:
        topic = topics[trace['topic_id']]
        plan = plans.get(trace.get('planned_slide_id'))
        chart_ids = _ids(trace.get('chart_ids'))
        source_ids = _ids(trace.get('observation_ids'))
        source_ids.update(oid for cid in chart_ids if cid in charts
                          for oid in [*charts[cid].observation_ids, *charts[cid].total_observation_ids])
        memberships, outside, unknown = [], [], []
        for sid in topic.series_ids:
            owned = {item.id for item in lookup.get(sid, [])}
            matched = owned & source_ids
            if not owned:
                unknown.append(sid)
            elif not matched:
                outside.append(sid)
            else:
                memberships.append(dict(series_id=sid,
                    input_membership='complete' if matched == owned else 'partial',
                    matched_observation_count=len(matched), series_observation_count=len(owned)))
        numbers = sorted({number for number in trace.get('slide_numbers', [])
                          if isinstance(number, int) and not isinstance(number, bool) and number > 0})
        groups.append(dict(topic_id=topic.id, planned_slide_id=trace.get('planned_slide_id'),
            physical_slide_numbers=numbers, measured_physical_slides=len(numbers),
            layout=plan.layout if plan else None,
            visual_roles=sorted({block.role for block in plan.visual_blocks}) if plan else [],
            chart_ids=sorted(chart_ids), owning_series_ids=[item['series_id'] for item in memberships],
            series_input_membership=memberships, topic_series_outside_this_group=outside,
            unknown_topic_series_ids=unknown, unknown_chart_ids=sorted(chart_ids-charts.keys()),
            planned_slide_found=plan is not None,
            co_located_groups=[dict(physical_slide=number,
                planned_slide_ids=sorted(value for value in page_owners[number] if isinstance(value, str)))
                for number in numbers if len(page_owners[number]) > 1],
            mapping_basis='Recorded renderer input scope, not claim-by-claim display proof or predicted subset cost.'))
    return groups
