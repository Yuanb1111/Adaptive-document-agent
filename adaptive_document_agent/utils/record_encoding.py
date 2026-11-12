"""Lossless column encoding for repeated structured evidence records."""
import json

TABLE = '$record_table'
LITERAL = '$literal_object'
INSTRUCTIONS = ('Evidence uses lossless column encoding: {"$record_table":{"columns":[...],'
    '"rows":[...]}} represents an array of records; match each row cell to its column name. '
    'An optional constants object supplies identical fields inherited by EVERY row; '
    'columns lists only the varying fields. Nested cells use the same encoding. '
    '{"$literal_object":[[key,value],...]} escapes a literal '
    'object with reserved keys. All values, nulls, row ordering and geometry are unchanged.')


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def encode_records(value):
    if isinstance(value, dict):
        if set(value) in ({TABLE}, {LITERAL}):
            return {LITERAL: [[k, encode_records(v)] for k, v in value.items()]}
        return {k: encode_records(v) for k, v in value.items()}
    if not isinstance(value, list):
        return value
    encoded = [encode_records(v) for v in value]
    if len(value) < 2 or not all(isinstance(v, dict) for v in value):
        return encoded
    columns = list(value[0])
    if not columns or any(set(v) != set(columns) for v in value):
        return encoded
    table = {TABLE: dict(columns=columns,
        rows=[[encode_records(v[k]) for k in columns] for v in value])}
    # JSON identity keeps bool/int/float distinctions, including nested values.
    signature = lambda cell: json.dumps(cell, ensure_ascii=False, sort_keys=True)
    constants = {key: value[0][key] for key in columns
                 if len({signature(row[key]) for row in value}) == 1}
    varying = [key for key in columns if key not in constants]
    factored = {TABLE: dict(columns=varying, constants=encode_records(constants),
        rows=[[encode_records(row[key]) for key in varying] for row in value])}
    return min((encoded, table, factored), key=_size)


def decode_records(value):
    """Used by offline verification; the wire format is explicitly self-describing."""
    if isinstance(value, list):
        return [decode_records(v) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {LITERAL}:
        return {k: decode_records(v) for k, v in value[LITERAL]}
    if set(value) == {TABLE}:
        table = value[TABLE]
        constants = decode_records(table.get('constants', {}))
        return [{**constants, **dict(zip(table['columns'], (decode_records(v) for v in row), strict=True))}
                for row in table['rows']]
    return {k: decode_records(v) for k, v in value.items()}
