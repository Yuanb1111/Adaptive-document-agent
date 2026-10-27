"""Arithmetic reference options for disjoint measured topics; no priority decisions."""
from itertools import combinations


def whole_topic_cost_options(counts, allocation):
    """Enumerate bounded whole-topic subsets without estimating partial-series savings."""
    result = dict(
        basis='Reference costs of complete unchanged measured topics with current other pages. '
              'New copy, layout or briefing can change costs; final native checks remain mandatory. '
              'These are arithmetic options, not source-meaning approval or importance rankings.',
        options=[])
    topics = counts.get('topic_pages', [])
    ids = [topic['topic_id'] for topic in topics]
    if not 1 <= len(ids) <= 8 or len(ids) != len(set(ids)):
        return dict(result, status='unavailable', reason='Requires one to eight uniquely identified measured topics.')
    pages = {topic_id: set() for topic_id in ids}
    for group in counts.get('native_groups', []):
        if group.get('topic_id') not in pages:
            return dict(result, status='unavailable', reason='Native group ownership is incomplete.')
        pages[group['topic_id']].update(group.get('physical_slide_numbers', []))
    costs = {topic['topic_id']: topic['physical_slides'] for topic in topics}
    if (any(not pages[topic_id] or len(pages[topic_id]) != costs[topic_id] for topic_id in ids)
            or sum(costs.values()) != counts['analysis']
            or len(set().union(*pages.values())) != counts['analysis']):
        return dict(result, status='unavailable', reason='Topic pages are missing, shared or not additive; no subset savings inferred.')
    capacity = allocation['effective_analysis_capacity']
    for size in range(1, len(ids) + 1):
        for retained in combinations(ids, size):
            cost = sum(costs[topic_id] for topic_id in retained)
            if cost > capacity or any(cap['current_non_analysis_slides'] + cost > cap['maximum_slides']
                                      for cap in allocation['constraints']):
                continue
            result['options'].append(dict(option_id=f'scope{len(result["options"])}', retained_topic_ids=list(retained),
                omitted_topic_ids=[topic_id for topic_id in ids if topic_id not in retained],
                measured_analysis_slides=cost,
                report_scopes_with_current_other_pages=[dict(slide_scope=cap['slide_scope'],
                    projected_slides=cap['current_non_analysis_slides'] + cost,
                    maximum_slides=cap['maximum_slides']) for cap in allocation['constraints']]))
    return dict(result, status='available')
