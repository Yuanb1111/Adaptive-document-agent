"""Grouped units, split date headers and unresolvable geometry stay source-bound."""
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from tests.test_borderless_alignment_regressions import PositionedPage, TextPage, result_for
from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data


class MixedPage(PositionedPage):
    def __init__(self):
        self.words = []
        for title,x in [('Installed capacity',230),('Output volume',390),('Utilization(2)',550)]:
            self.word(title,10,x)
        for x in (290,450,610):
            self.word('Firsthalf',25,x)
        for i in range(12):
            self.word(['2021','2022','2023','of2024'][i%4],40,170+i*40)
        for unit,x in [('(units)',230),('(units)',390),('(%)',550)]:
            self.word(unit,55,x)
        for label,y,values in [
            ('Alpha',75,['—','23,951','24,936','10,422','—','7,871','9,438','4,583','—','32.9','37.8','44.0']),
            ('Beta',95,['—','4,472','4,832','2,384','—','2,619','2,963','1,688','—','58.6','61.3','70.8']),
        ]:
            self.word(label,y,40)
            for i,value in enumerate(values):
                self.word(value,y,170+i*40)


def test_grouped_units_and_half_years_preserve_raw_values_and_pages():
    table = BorderlessTableExtractor().extract(MixedPage(),245)[0]
    assert table.column_types == ['label']+['count']*8+['percentage']*4
    assert table.column_periods == [None]+['2021','2022','2023','1H2024']*3
    assert table.default_unit is None
    assert '(units) (units) (%)' in table.raw_header_lines
    observations = ObservationExtractor()._table_observations(table)
    quantity = next(o for o in observations if o.raw_value=='23,951')
    rate = next(o for o in observations if o.raw_value=='32.9')
    assert (quantity.value,quantity.unit,quantity.unit_scale)==(23951,'count',1)
    assert (rate.value,rate.unit)==(32.9,'percent')
    assert quantity.evidence[0].page==245
    assert table.raw_cells[0][2]=='23,951'
    assert not validate_presentation_data(result_for(table))


def test_missing_geometry_cannot_spread_percent_to_unknown_columns():
    source = TextPage('''Operations
Firsthalf Firsthalf Firsthalf
2021 2022 2023 of2024 2021 2022 2023 of2024 2021 2022 2023 of2024
(units) (units) (%)
Alpha ... — 23,951 24,936 10,422 — 7,871 9,438 4,583 — 32.9 37.8 44.0
Beta ... — 4,472 4,832 2,384 — 2,619 2,963 1,688 — 58.6 61.3 70.8''')
    table = BorderlessTableExtractor().extract(source,1)[0]
    assert table.default_unit is None
    assert table.column_periods[4] is None
    assert not any(o.unit=='percent' for o in ObservationExtractor()._table_observations(table))


def test_date_fragments_and_labelled_year_header_are_not_numeric_rows():
    source = TextPage('''Environmental measures
Six months
Year ended December 31,
ended June 30,
Emissions 2021 2022 2023 2024
Direct emissions ... 10 20 30 40
Indirect emissions ... 20 40 60 80''')
    table = BorderlessTableExtractor().extract(source,264)[0]
    assert [r.cells[0] for r in table.rows]==['Direct emissions','Indirect emissions']
    assert 'Year ended December 31,' in table.raw_header_lines
    assert 'Emissions 2021 2022 2023 2024' in table.raw_header_lines
    assert not any(i.code=='ambiguous_table_alignment' for i in validate_presentation_data(result_for(table)))


def test_amounts_resembling_years_remain_body_values():
    source = TextPage('''Counts
Year ended December 31,
2023 2024
Orders ... 2021 2022
Shipments ... 3000 4000''')
    table = BorderlessTableExtractor().extract(source,1)[0]
    assert table.rows[0].cells == ['Orders','2021','2022']
    assert len(table.rows)==2


def test_body_section_row_cannot_overwrite_geometric_units_during_reconstruction():
    from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
    from adaptive_document_agent.models.table import TableRow
    extracted = BorderlessTableExtractor().extract(MixedPage(), 245)[0]
    extracted.raw_cells.insert(0, ['Finished products'] + [None] * 12)
    extracted.rows.insert(0, TableRow(cells=extracted.raw_cells[0], page=245, is_section_header=True))
    repaired = TableReconstructor().reconstruct(extracted)
    assert repaired.headers == [' '.join(h.split()) for h in extracted.headers]
    assert repaired.column_types == ['label'] + ['count'] * 8 + ['percentage'] * 4
    assert repaired.column_periods == extracted.column_periods
    assert repaired.raw_cells == extracted.raw_cells
    assert repaired.rows[0].is_section_header
    rate = next(o for o in ObservationExtractor()._table_observations(repaired) if o.raw_value == '32.9')
    assert rate.value == 32.9 and rate.unit == 'percent'
