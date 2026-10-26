"""Lossless wire dictionaries for repeated cells, with literal selectable IDs."""

import json


def dictionary_columns(rows, columns, *, literal=('id',)):
    """Replace a repeated column only when its dictionary saves transport space.

    Callers own the wire copy. No source records, cell contents or ordering are
    changed; null, empty, numeric and string cells retain distinct JSON types.
    """
    dictionaries = {}
    for index, field in enumerate(columns):
        if field in literal or not rows:
            continue
        values, positions, cells = [], {}, []
        for row in rows:
            key = json.dumps(row[index], ensure_ascii=False, separators=(',', ':'))
            if key not in positions:
                positions[key] = len(values)
                values.append(row[index])
            cells.append(positions[key])
        original = sum(len(json.dumps(row[index], ensure_ascii=False)) for row in rows)
        encoded = len(json.dumps(values, ensure_ascii=False)) + len(json.dumps(cells)) + len(field) + 250
        if encoded < original:
            dictionaries[field] = values
            for row, cell in zip(rows, cells):
                row[index] = cell
    return dictionaries


def factor_series_cells(payload):
    """Reference repeated evidence cells once; retain every series and note."""
    columns = payload.get('series_columns', [])
    if columns and not payload.get('series_value_dictionaries'):
        # Keep the selectable handle adjacent to its human-readable identity.
        # Indirection here is lossless for Python but makes model ID selection
        # unnecessarily depend on joining a second dictionary correctly.
        dictionaries = dictionary_columns(payload.get('all_extracted_series', []), columns,
                                          literal=('id', 'metric', 'canonical_metric'))
        if dictionaries:
            payload['series_value_dictionaries'] = dictionaries
            payload['series_cell_encoding'] = (
                'Rows follow series_columns. For a column named in series_value_dictionaries, '
                'the cell is a zero-based index into that column dictionary; otherwise it is literal. '
                'Resolve these cells BEFORE applying point_encoding. Every exact value, label, '
                'qualification and source page remains present. Series IDs stay literal.')
    for field, content in (('source_row_qualifications', 'notes'), ('ratio_definitions', 'definitions')):
        entries = payload.get(field, [])
        if not entries or not all(set(row) == {'series_id', content} for row in entries):
            continue
        rows = [[row['series_id'], row[content]] for row in entries]
        dictionaries = dictionary_columns(rows, ['series_id', content], literal=('series_id',))
        if dictionaries:
            payload[field] = [dict(series_id=row[0], **{content + '_ref': row[1]}) for row in rows]
            payload[field + '_dictionary'] = dictionaries[content]
            payload[field + '_encoding'] = (
                f'{content}_ref is a zero-based index into {field}_dictionary. '
                'Each referenced list preserves complete source content and ownership; no item is omitted.')
    return payload
