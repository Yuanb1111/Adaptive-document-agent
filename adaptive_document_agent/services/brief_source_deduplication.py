"""Show exact corroborating summary series once, preserving cited sources."""

from adaptive_document_agent.document_model.series import metric_identity_key
from .presentation_labels import qualified_metric_name


def _signature(chart, index):
    points = []
    for identifier in chart.observation_ids:
        item = index.get(identifier)
        if item is None:
            return frozenset()
        identity = metric_identity_key(item)
        # Generic labels retain their table identity in the extended key.
        scope = identity if len(identity) != 7 else (identity[0], *identity[2:])
        points.append((scope, qualified_metric_name(item), item.parent_section,
                       item.value, item.raw_value, item.unit, item.raw_unit, item.unit_scale,
                       item.period, item.period_basis, item.period_type, item.as_of_date,
                       item.period_start, item.period_end, item.audited_status, item.fact_type))
    return frozenset(points)


def deduplicate_brief_facts(facts, index):
    """Only an exact subset can corroborate the fuller selected source series."""
    retained = []
    for fact in facts:
        signature = _signature(fact['chart'], index)
        match = next((old for old in retained if signature and old['signature']
                      and (signature <= old['signature'] or old['signature'] <= signature)), None)
        if match is None:
            retained.append({**fact, 'pages': set(fact['pages']), 'signature': signature})
        else:
            pages = match['pages'] | set(fact['pages'])
            if len(signature) > len(match['signature']):
                match.update(fact, signature=signature)
            match['pages'] = pages
    return retained
