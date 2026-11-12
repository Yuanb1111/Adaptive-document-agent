"""Wire compression must retain every literal type, value and record."""
import json

import pytest

from adaptive_document_agent.utils.record_encoding import encode_records, decode_records, TABLE


def test_repeated_metadata_is_inherited_without_dropping_blank_values_or_geometry():
    rows = [dict(raw=f'({n}.00)', unit='RMB in thousands', status='unknown', optional=None,
                 bbox=[1.125, 2.25, 3.5, 4.75]) for n in range(30)]
    wire = encode_records(rows)
    assert wire[TABLE]['constants']['optional'] is None
    assert wire[TABLE]['columns'] == ['raw']
    assert decode_records(wire) == rows
    assert len(json.dumps(wire)) < len(json.dumps(rows)) / 2


@pytest.mark.parametrize('cells', [[True, 1, 1.0], [[True], [1], [1.0]],
    [{'x': True}, {'x': 1}, {'x': 1.0}], [-0.0, 0.0, 0]])
def test_equal_python_values_do_not_erase_distinct_json_types(cells):
    rows = [dict(unit='A long shared literal unit', raw=cell) for cell in cells]
    decoded = decode_records(encode_records(rows))
    assert json.dumps(decoded) == json.dumps(rows)


def test_all_constant_rows_retain_multiplicity_and_reserved_literal_objects():
    rows = [dict(note={'$record_table': {'constants': {'raw': 'literal'}}}, empty='')] * 12
    assert decode_records(encode_records(rows)) == rows
