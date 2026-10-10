"""Verify implemented native formatting and source footers, not model promises."""
from .fourier_brand import PRIMARY, WHITE


def table_presentation_errors(presentation):
    errors, numbers = [], []
    for number, slide in enumerate(presentation.slides,1):
        for shape in slide.shapes:
            if not shape.has_table or not shape.name.startswith('customization:source_table:'):
                continue
            numbers.append(number)
            for cell in shape.table.rows[0].cells:
                if str(cell.fill.fore_color.rgb) != PRIMARY:
                    errors.append(f'Slide {number}: source header is not purple')
                for p in cell.text_frame.paragraphs:
                    if not p.font.bold or str(p.font.color.rgb) != WHITE:
                        errors.append(f'Slide {number}: source header needs bold white text')
            for row in shape.table.rows:
                for cell in row.cells:
                    if any(not p.font.size or p.font.size.pt < 11 for p in cell.text_frame.paragraphs):
                        errors.append(f'Slide {number}: source table type is below 11 pt')
                    if any(not cell._tc.xpath('./a:tcPr/a:'+edge+'/a:solidFill')
                           for edge in ('lnL','lnR','lnT','lnB')):
                        errors.append(f'Slide {number}: source cell lacks visible grid borders')
    if not numbers:
        errors.append('No requested source tables were exported')
    return sorted(set(errors)), sorted(set(numbers))


def citation_errors(presentation, result):
    errors, checked = [], []
    required = {n for record in result.presentation_export_trace if record.get('source_pages')
                for n in record.get('slide_numbers',[])}
    required.update(n for n,s in enumerate(presentation.slides,1)
                    if any(sh.name.startswith('customization:source_table:') for sh in s.shapes))
    for n in sorted(required):
        if not 1 <= n <= len(presentation.slides):
            errors.append(f'Source mapping refers to absent slide {n}')
            continue
        footers = [sh.text for sh in presentation.slides[n-1].shapes if sh.has_text_frame
                   and sh.text.strip().startswith('Source: Document disclosures (p. ')]
        if not footers:
            errors.append(f'Slide {n}: source page footer missing')
        else:
            checked.append(n)
    if not required:
        errors.append('No source-bound exported slides available for verification')
    return errors, checked
