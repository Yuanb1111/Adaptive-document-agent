"""Attached source notes do not erase periods or subscript labels."""
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.borderless_layout import source_lines


def test_annotated_year_tier_is_header_without_treating_accounting_values_as_dates():
    parser=BorderlessTableExtractor()
    header=['Year ended December 31,', 'Pollutant 2021(1) 2022(1) 2023 2024', 'PM (kg) N/A N/A 0.066 0.109']
    assert parser._nearest_year_header(header,2)==(1,['2021','2022','2023','2024'])
    assert parser._nearest_year_header(['Costs 2021 (500) 2022 (600)',''],1)==(None,[])


def test_subscript_glyph_is_preserved_only_with_adjacent_overlapping_geometry():
    words=[dict(text='NO',x0=10,x1=25,top=10,bottom=20),
           dict(text='x',x0=25.5,x1=29,top=14,bottom=21),
           dict(text='(kg)',x0=35,x1=55,top=10,bottom=20),
           dict(text='1.461',x0=100,x1=130,top=10,bottom=20)]
    lines=source_lines(object(),'',lambda x:x,words=words)
    assert len(lines)==1 and lines[0].text=='NOx (kg) 1.461'
    assert lines[0].bounds(0,3)==(10,29)
    words[1]['x0']=70;words[1]['x1']=75
    lines=source_lines(object(),'',lambda x:x,words=words)
    assert len(lines)==2
