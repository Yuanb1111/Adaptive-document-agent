"""Factor exact repeated merge metadata without discarding any source facts."""

import json

from .coverage_review_context import encode


def encode_merge_context(context):
    """Keep literal series IDs and point grids; dictionary repeated row cells.

    A final merge can contain many related period/category views. Their repeated
    exact metadata can exceed the request budget even after point compaction.
    Each dictionary is reversible, with every value and series retained. This
    changes only the wire encoding, never importance, scope or selected evidence.
    """
    original = encode(context)
    payload = json.loads(original)
    rows = payload.get('all_extracted_series', [])
    columns = payload.get('series_columns', [])
    if not rows or not columns or payload.get('series_value_dictionaries'):
        return original
    dictionaries = {}
    for index, field in enumerate(columns):
        if field in {'id', 'reported_points'}:
            continue  # Model choices and complete ordered point cells stay literal.
        values, positions, cells = [], {}, []
        for row in rows:
            key = json.dumps(row[index], ensure_ascii=False, separators=(',', ':'))
            if key not in positions:
                positions[key] = len(values)
                values.append(row[index])
            cells.append(positions[key])
        original_size = sum(len(json.dumps(row[index], ensure_ascii=False,
                                         separators=(',', ':'))) for row in rows)
        compact_size = (len(json.dumps(values, ensure_ascii=False, separators=(',', ':')))
                        + sum(len(str(cell)) for cell in cells) + len(field) + 10)
        if compact_size >= original_size:
            continue
        dictionaries[field] = values
        for row, cell in zip(rows, cells):
            row[index] = cell
    if not dictionaries:
        return original
    payload['series_value_dictionaries'] = dictionaries
    payload['series_metadata_encoding'] = (
        'Series rows follow series_columns. For columns named in series_value_dictionaries, '
        'each cell is a zero-based index into that column dictionary; resolve it BEFORE '
        'reading point_constants and point_columns. Other cells are literal. All series, '
        'ordered points, exact source metadata and qualifications remain present.')
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return encoded if len(encoded) < len(original) else original
