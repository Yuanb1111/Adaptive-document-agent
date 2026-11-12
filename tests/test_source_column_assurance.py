"""A literal marker belongs to its checked header cell, including after a Notes column."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models import ExtractedTable
from adaptive_document_agent.extraction.source_column_assurance import literal_column_statuses
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.agent.brief_audit_scope import geometric_column_statuses
from tests.test_retained_audit_scope import positioned


def literal():
    header=[['','','Year ended 31 December','','','Six months ended 30 June',''],
        ['','Notes','2021','2022','2023','2023','2024'],
        ['','','RMB000','RMB000','RMB000','RMB000','RMB000'],
        ['','','','','','(Unaudited)','']]
    return ExtractedTable(table_id='literal',page=1,raw_header_cells=header,
        raw_header_spans=[(0,2,4),(0,5,6)],raw_header_lines=[' '.join(r) for r in header],
        raw_cells=[['Revenue','7','10','20','30','40','50']],source_layout_status='checked')


def test_literal_notes_column_preserves_only_its_exact_interim_assurance_before_observation_creation():
    original=literal();before=deepcopy(original)
    analytical=TableExtractor()._analytical_copy(original)
    assert analytical.column_periods==[None,None,'FY2021','FY2022','FY2023','6M2023','6M2024']
    assert analytical.column_audit_statuses==['unknown']*5+['unaudited','unknown']
    observations=ObservationExtractor()._table_observations(analytical)
    assert len(observations)==5
    assert next(o for o in observations if o.period=='6M2023').audited_status=='unaudited'
    assert next(o for o in observations if o.period=='6M2024').audited_status=='unknown'
    assert original==before and analytical.raw_cells==original.raw_cells


@pytest.mark.parametrize('mutation',['unchecked','group_marker','prose','reference'])
def test_marker_cannot_be_borrowed_from_unchecked_group_prose_or_reference_column(mutation):
    table=literal();periods=[None,None,'FY2021','FY2022','FY2023','6M2023','6M2024']
    if mutation=='unchecked':table.source_layout_status='unchecked'
    elif mutation=='group_marker':table.raw_header_spans.append((3,5,6))
    elif mutation=='prose':table.raw_header_cells[3][5]='These figures may be unaudited.'
    else:table.raw_header_cells[3][1]=table.raw_header_cells[3][5];table.raw_header_cells[3][5]=''
    assert literal_column_statuses(table,periods)==['unknown']*7


def test_independent_geometry_ignores_reference_columns_when_matching_period_anchors(positioned):
    result,_=positioned;page=result.document.pages[0];table=page.tables[0]
    table.headers.insert(1,'Notes');table.column_periods.insert(1,None)
    table.column_audit_statuses.insert(1,'unknown');table.rows[0].cells.insert(1,'7')
    assert geometric_column_statuses(page,table,['(unaudited)'])==[None,'unaudited','unknown','unknown']


def test_independent_geometry_reads_ruled_headers_inside_their_own_grid_box(positioned):
    result,_=positioned;page=result.document.pages[0];table=page.tables[0]
    table.source_layout_status='checked';table.bbox=(0,0,350,160)
    table.raw_header_cells=[['','2023','2024','2025']]
    body='Revenue '+' '.join(o.raw_value for o in result.observations)
    table.raw_body_lines=[body]
    page.text_blocks[0]['lines'].append(dict(text=body,bbox=[0,120,340,130]))
    assert geometric_column_statuses(page,table,['(unaudited)'])==['unaudited','unknown','unknown']
