"""Positioned unit headers bind only their own adjacent source cell."""
from copy import deepcopy
import os
from pathlib import Path

import pytest

from adaptive_document_agent.models import DocumentPage, PipelineResult
from adaptive_document_agent.extraction.source_geometry import rotate_box
from adaptive_document_agent.services.brief_column_quantities import column_quantities, quoted_column_quantities


def page(rotation=0):
    lines = [('(HK$ in', [100, 20, 130, 26]), ('million)', [100, 30, 130, 36]),
             ('12.5', [108, 44, 122, 50]), ('Other project', [180, 44, 230, 50]),
             ('98.7', [190, 54, 210, 60])]
    return DocumentPage(page_number=1, text='\n'.join(t for t, _ in lines), reading_rotation=rotation,
        text_blocks=[dict(lines=[dict(text=t, bbox=list(rotate_box(b, 0, 0, (360-rotation) % 360)))
                                for t, b in lines])])


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_column_geometry_binds_exact_unit_and_preserves_original_page(rotation):
    source = page(rotation)
    before = source.model_dump()
    pairs = column_quantities(source)
    assert [(v['raw_value'], v['currency'], v['unit']) for v in pairs] == [('12.5', 'HKD', 'million')]
    assert quoted_column_quantities(source, '(HK$ in\nmillion)\n12.5', source.text) == {('hk$', '12.5', 'million')}
    assert not quoted_column_quantities(source, 'The figure is 12.5', source.text)
    assert not quoted_column_quantities(source, source.text, '12.5')
    assert source.model_dump() == before


@pytest.mark.parametrize('fault', ['intervening', 'two_cells', 'different_column', 'missing_layout', 'missing_header', 'far_cell'])
def test_ambiguous_or_incomplete_column_geometry_confers_no_unit(fault):
    source = page()
    lines = source.text_blocks[0]['lines']
    if fault == 'intervening':
        lines.append(dict(text='Not applicable', bbox=[100, 38, 130, 42]))
        source.text += '\nNot applicable'
    elif fault == 'two_cells':
        lines.append(dict(text='13.5', bbox=[108, 44, 122, 50]))
        source.text += '\n13.5'
    elif fault == 'different_column':
        lines[2]['bbox'] = [150, 44, 165, 50]
    elif fault == 'missing_layout':
        source.text_blocks = []
    elif fault == 'missing_header':
        source.text = '12.5 Other project 98.7'
    else:
        lines[2]['bbox'] = [108, 100, 122, 106]
    assert column_quantities(source) == []


def test_numbered_sources_keep_original_spatial_evidence_for_writer_and_reviewer():
    from adaptive_document_agent.agent.audit_source_layout import audit_source_page
    from adaptive_document_agent.agent.source_integration_quotes import numbered_source_pages
    source = page(90)
    payload = dict(**audit_source_page(source, reading_orientation=True),
                   verified_quantity_columns=column_quantities(source), has_structured_tables=False)
    numbered, = numbered_source_pages([payload])
    assert numbered['layout_lines'] == payload['layout_lines']
    assert numbered['layout_rotation'] == 90
    assert numbered['verified_quantity_columns'] == payload['verified_quantity_columns']


@pytest.mark.parametrize('other', ['112.5', '-12.5', '12.50', '12.5%'])
def test_quote_cannot_borrow_a_substring_from_a_different_value(other):
    source = page()
    source.text += '\n(HK$ in\nmillion)\n' + other
    assert not quoted_column_quantities(source, '(HK$ in\nmillion)\n' + other, source.text)


def test_recorded_rotated_project_costs_pass_literal_numeric_binding():
    path = os.environ.get('ADA_SELECTION_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_SELECTION_DIAGNOSTIC to the private .732 source diagnostic')
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    result = PipelineResult.model_validate_json(Path(path).read_text(encoding='utf-8'))
    original = deepcopy(result.document)
    for number, amount in [(183, '49.9'), (184, '27.2'), (185, '13.6')]:
        source = next(p for p in result.document.pages if p.page_number == number)
        assert column_quantities(source)[0]['raw_value'] == amount
        quote = '\n'.join(source.text.splitlines()[:10])
        brief = ExecutiveBrief.model_validate(dict(items=[dict(label='Source estimate',
            text=f'The disclosed estimate is HK${amount} million.', evidence=[dict(page=number, text=quote)])]))
        assert not validate_executive_brief(brief, result)
    assert result.document == original
