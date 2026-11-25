"""Source comparisons are literal, editable and cannot omit conditional cases."""
import pytest
from pptx import Presentation
from pptx.util import Inches
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, BriefComparisonTable
from adaptive_document_agent.services.executive_brief import validate_executive_brief, brief_items
from adaptive_document_agent.services.presentation_summary import render_complete_summary
from tests.test_executive_brief import result_for, payload


def fixture():
    text = 'Response time is estimated at 44 months without expansion, 60 months with partial expansion and 89 months with full expansion.'
    result = result_for([text])
    data = payload('Response time estimates depend on expansion assumptions.', label='Response scenarios')
    data['items'][0]['evidence'][0]['text'] = text
    data['items'][0]['comparison_table'] = {'headers': ['Assumption', 'Estimated response time'],
        'rows': [['without expansion', '44 months'], ['with partial expansion', '60 months'],
                 ['with full expansion', '89 months']]}
    brief = ExecutiveBrief.model_validate(data)
    return result, brief


def test_source_scenarios_are_editable_with_all_values_and_qualifiers():
    result, brief = fixture()
    before = result.model_dump(), brief.model_dump()
    assert not validate_executive_brief(brief, result)
    result.executive_brief = brief
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    slides = render_complete_summary(deck, brief.title, brief_items(result))
    assert len(slides) == 1
    table = next(s.table for s in slides[0].shapes if s.has_table)
    assert [[cell.text for cell in row.cells] for row in table.rows] == [brief.items[0].comparison_table.headers,
                                                                     *brief.items[0].comparison_table.rows]
    assert '44 months' in slides[0].notes_slide.notes_text_frame.text
    assert 'estimates' in ' '.join(s.text for s in slides[0].shapes if s.has_text_frame)
    result.executive_brief = None
    assert (result.model_dump(), brief.model_dump()) == before


@pytest.mark.parametrize('fault', ['value', 'unit', 'case', 'invented_assumption'])
def test_table_cannot_invent_values_units_or_lose_conditional_cases(fault):
    result, brief = fixture()
    table = brief.items[0].comparison_table
    if fault == 'value': table.rows[0][1] = '45 months'
    if fault == 'unit': table.rows[0][1] = '44 years'
    if fault == 'case': table.rows.pop(1)
    if fault == 'invented_assumption': table.rows[0][0] = 'without recruitment'
    assert validate_executive_brief(brief, result)


def test_table_requires_rectangular_bounded_cells():
    with pytest.raises(ValueError):
        BriefComparisonTable(headers=['Case', 'Outcome'], rows=[['A']])


def test_literal_accounting_cells_keep_signs_without_magnitude_annotations():
    from tests.test_brief_quantity_representation import magnitude_fixture
    result, brief = magnitude_fixture()
    item = brief.items[0]
    item.text = 'The reported source row retains signed values.'
    item.quantity_representations = []
    item.comparison_table = BriefComparisonTable(headers=['Measure', 'USD in thousands'],
                                               rows=[['Net loss', '(100)'], ['Net loss', '(200)']])
    assert not validate_executive_brief(brief, result)
    item.comparison_table.rows[0][1] = '100'
    assert validate_executive_brief(brief, result)

def test_table_does_not_isolate_the_last_ordinary_finding():
    from adaptive_document_agent.services.presentation_brief import BriefItem
    from tests.test_presentation_brief import blank_deck
    table = BriefComparisonTable(headers=['Case', 'Estimate'], rows=[['Base case', '44 months']])
    first = BriefItem('First finding', 'Complete source-supported finding and qualification. ' * 3, [1])
    last = BriefItem('Last finding', 'Final source-supported finding and qualification. ' * 3, [3])
    pages = render_complete_summary(blank_deck(), 'Summary', [first,
        BriefItem('Scenario', 'Conditional estimate.', [2], table=table), last], single_column=True)
    assert len(pages) == 2
    copy = '\n'.join(s.text for s in pages[0].shapes if s.has_text_frame)
    assert first.text in copy and last.text in copy
    assert any(s.has_table for s in pages[1].shapes)

def test_complete_literal_duration_cell_can_restore_unit_from_explicit_header():
    from adaptive_document_agent.services.brief_table_units import literal_table_units
    result, brief = fixture()
    item = brief.items[0]
    item.comparison_table.headers[1] = 'Estimated response time (months)'
    item.comparison_table.rows[1][1] = '60'
    before = brief.model_dump()
    assert not validate_executive_brief(brief, result)
    table = literal_table_units(item, {1: result.document.pages[0].text})
    assert table.rows[1][1] == '60 months'
    assert brief.model_dump() == before
    item.comparison_table.rows[1][1] = '61'
    assert validate_executive_brief(brief, result)


def test_budgeted_comparison_paginates_whole_qualified_rows_under_the_actual_title():
    from adaptive_document_agent.services.presentation_brief import BriefItem
    from tests.test_presentation_brief import blank_deck

    rows = [[f'Region {i}: ' + 'whole items enter the weekly count after verification ' * 2,
             'The count is current at the end of the week and may change when more items are returned.']
            for i in range(7)]
    table = BriefComparisonTable(headers=['Case under review', 'Method applied to observations'], rows=rows)
    item = BriefItem('Collection conditions',
                     'The counts depend on the collection date and include each returning participant once. ' * 5,
                     [5], table=table, conditions='Collected as of the stated date.')
    ordinary = render_complete_summary(blank_deck(), 'Conclusion', [item])
    assert len(ordinary) == 3
    compact = render_complete_summary(blank_deck(), 'Conclusion', [item], fit_page_budget=True)
    assert len(compact) == 2
    visible_rows = []
    for slide in compact:
        heading = next(s for s in slide.shapes if s.name == 'brief:heading')
        assert all(p.top + p.height < heading.top for p in slide.placeholders if p.has_text_frame and p.text.strip())
        native = next(s.table for s in slide.shapes if s.has_table)
        assert [cell.text for cell in native.rows[0].cells] == table.headers
        visible_rows.extend([cell.text for cell in row.cells] for row in list(native.rows)[1:])
        assert all(c.text_frame.paragraphs[0].font.size.pt >= 14 for row in native.rows for c in row.cells)
        assert any(s.has_text_frame and s.text == item.conditions for s in slide.shapes)
    assert visible_rows == rows
    body = next(s for s in compact[0].shapes if s.name == 'brief:body')
    assert body.text == item.text and body.text_frame.paragraphs[0].font.size.pt >= 14
