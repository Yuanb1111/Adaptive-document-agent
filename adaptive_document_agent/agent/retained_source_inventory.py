"""Share the complete related source-series inventory across writer and reviewer."""


def complete_source_observations(result, anchor_ids):
    """Expand source context, never a finding's eligible numeric input rows."""
    ids=set(anchor_ids)
    ids.update(oid for task in result.analysis_results for oid in task.input_observation_ids)
    from .presentation_topic_selector import series_directory
    _,lookup=series_directory(result)
    for group in lookup.values():
        if ids & {o.id for o in group}:
            ids.update(o.id for o in group)
    return [o for o in result.observations if o.id in ids]
