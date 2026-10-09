"""Complete bounded coverage contexts; compact repeated metadata, never facts."""
from copy import deepcopy
import json


def encode(payload):
    rows = payload.get('all_extracted_series', [])
    if payload.get('point_encoding') and rows and isinstance(rows[0], dict):
        # Columnar encoding removes repeated field names, not source content.
        fields = list(dict.fromkeys(key for row in rows for key in
                      [*row['point_constants'], *row['point_columns']]))
        entries = []
        for row in rows:
            entries.append({**row,
                'point_constants': [[fields.index(key), value] for key, value in row['point_constants'].items()],
                'point_columns': [fields.index(key) for key in row['point_columns']]})
        columns = list(dict.fromkeys(key for row in entries for key in row))
        payload = {**payload, 'series_columns': columns, 'point_field_names': fields,
                   'all_extracted_series': [[row.get(key) for key in columns] for row in entries],
                   'point_encoding': ('Series rows follow series_columns. point_constants contains [field_index,value] pairs; '
                       'point_columns contains field indices into point_field_names. Every ordered point inherits '
                       'those constants and supplies its variable cells. All source points are present.')}
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def compact_context(payload):
    """Factor shared point columns and duplicate matrix cells out of the wire view.

    Observation IDs are kept in the exported data/series lookup; review selects
    series IDs only. Every raw/normalized value, period, unit, definition, audit
    status and source page is retained in order. No point or series is sampled.
    """
    compact = deepcopy(payload)
    columns = list(compact.get('series_columns', []))
    point_columns = list(compact.get('reported_point_columns', []))
    if 'reported_points' not in columns or not point_columns:
        return compact
    summaries = []
    for row in compact['all_extracted_series']:
        entry = dict(zip(columns, row))
        points = entry.pop('reported_points')
        facts = [dict(zip(point_columns, point)) for point in points]
        for fact in facts:
            fact.pop('observation_id', None)
        constants = {key: facts[0][key] for key in facts[0]
                     if all(fact[key] == facts[0][key] for fact in facts)} if facts else {}
        varying = [key for key in facts[0] if key not in constants] if facts else []
        # These values are exact duplicates of the ordered point view.
        for key in ('first_reported_value', 'last_reported_value', 'observation_count', 'periods'):
            entry.pop(key, None)
        # Matrix reported_values also binds each point to its category.
        # Keep that mapping: the point columns alone do not contain labels.
        entry['point_constants'] = constants
        entry['point_columns'] = varying
        entry['reported_points'] = [[fact[key] for key in varying] for fact in facts]
        summaries.append(entry)
    compact.pop('series_columns', None)
    compact.pop('reported_point_columns', None)
    compact['all_extracted_series'] = summaries
    compact['point_encoding'] = 'Each point inherits point_constants, then point_columns maps its ordered cells. All source points are present.'
    return compact


def batch_context(compact, selection, ids):
    """Show full facts for this batch and current selected evidence, plus a catalog."""
    selected = {sid for topic in selection.topics for sid in topic.series_ids}
    visible = selected | set(ids)
    rows = compact['all_extracted_series']
    result = {key: value for key, value in compact.items()
              if key not in {'all_extracted_series', 'same_source_row_period_views',
                             'ratio_definitions', 'series_requiring_coverage_decision'}}
    result['all_extracted_series'] = [row for row in rows if row['id'] in visible]
    # Catalog preserves global question context; omitted points are explicitly
    # deferred to other batches, never treated as absent or less important.
    catalog_columns = ['id', 'metric', 'unit', 'currency', 'source_pages', 'visual_kind']
    result['catalog_columns'] = catalog_columns
    result['complete_series_catalog'] = [[row.get(key) for key in catalog_columns] for row in rows]
    result['same_source_row_period_views'] = [view for view in compact.get('same_source_row_period_views', [])
        if any(entry['series_id'] in set(ids) for entry in view['same_source_row'])]
    result['ratio_definitions'] = [row for row in compact.get('ratio_definitions', []) if row['series_id'] in visible]
    result['current_selection'] = selection.model_dump(mode='json')
    result['series_requiring_coverage_decision'] = ids
    result['selectable_series_ids'] = sorted(visible)
    result['batch_scope'] = ('Only current selected series and this batch have full evidence. '
        'Other catalog entries are deferred to separate review batches. Retain current selected evidence; '
        'do not select, exclude or infer values for deferred series. Every batch is reviewed before committing changes.')
    return result
