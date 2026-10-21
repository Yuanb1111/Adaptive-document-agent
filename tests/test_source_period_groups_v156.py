"""Annual and interim leaf years retain their distinct, geometry-proved scopes."""
import pytest

from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.validation import ExtractionValidator
from tests.test_source_header_scope_v141 import analytical, literal


def test_grouped_duration_headers_with_notes_preserve_periods_and_original_cells():
    source = literal([
        ['', '', 'CONSOLIDATED STATEMENTS', '', '', '', ''],
        ['', '', 'Year ended 31 December', '', '', 'Six months ended 30 June', ''],
        ['', 'Notes', '2021', '2022', '2023', '2023', '2024'],
        ['', '', 'RMB’000', 'RMB’000', 'RMB’000', 'RMB’000', 'RMB’000'],
    ], [['Revenue', '5', '174,314', '241,013', '286,749', '109,912', '120,462']],
        spans=[(0, 2, 6), (1, 2, 4), (1, 5, 6)])
    table = analytical(source)
    assert table.column_periods == [None, None, 'FY2021', 'FY2022', 'FY2023', '6M2023', '6M2024']
    assert table.column_types[1] == 'reference'
    observations = ObservationExtractor()._table_observations(table)
    assert len(observations) == 5
    assert {(o.period, o.raw_value) for o in observations} >= {('FY2023', '286,749'), ('6M2023', '109,912')}
    assert not [i for i in ExtractionValidator().validate(observations).issues if i.code == 'conflicting_values']


@pytest.mark.parametrize('spans', [[], [(0, 1, 3)], [(0, 1, 2), (0, 2, 3)]])
def test_unproved_or_overlapping_period_groups_are_quarantined(spans):
    source = literal([['', 'Year ended 31 December', '', 'Six months ended 30 June'],
                      ['', '2022', '2023', '2023']], [['Volume', '10', '12', '6']], spans=spans)
    table = analytical(source)
    assert all(row.alignment_status == 'ambiguous' for row in table.rows)
    assert ObservationExtractor()._table_observations(table) == []


def test_aligned_snapshot_groups_do_not_turn_into_annual_flows():
    source = literal([['', 'As at 31 December', '', 'As at 30 June'],
                      ['', '2022', '2023', '2024']], [['Assets', '10', '12', '13']], spans=[(0, 1, 2)])
    table = analytical(source)
    assert table.column_periods == [None, '31 Dec 2022', '31 Dec 2023', '30 Jun 2024']


def test_wide_single_date_heading_keeps_its_words_on_the_proved_column():
    from adaptive_document_agent.extraction.source_geometry import Glyph, GeometryLine
    from adaptive_document_agent.extraction.ruled_source_tables import _header
    line = GeometryLine([Glyph('As', 180, 10, 190, 17, 7), Glyph('at', 192, 10, 199, 17, 7),
                         Glyph('30', 201, 10, 211, 17, 7), Glyph('June', 213, 10, 237, 17, 7)], 10, 17, 7)
    row, spans = _header(line, [(145, 155, 'right'), (205, 215, 'right')], [], 50, 250)
    assert row == ['', '', 'As at 30 June']
    assert not spans


def test_incomplete_snapshot_date_is_not_replaced_by_an_annual_guess():
    source = literal([['', 'As at', ''], ['', '2023', '2024']], [['Assets', '10', '12']], spans=[(0, 1, 2)])
    table = analytical(source)
    assert ObservationExtractor()._table_observations(table) == []
