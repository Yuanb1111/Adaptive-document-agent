"""Readable editable tables for model-authored literal source comparisons."""
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from .brief_comparison_layout import comparison_layout, page_tops, table_geometries
from .presentation_brief import BODY_PT, _copy_height


def render_comparison(presentation, title, item, *, notes='', fit_page_budget=False):
    """Fit complete comparisons by measured column widths, preserving conditions."""
    from .slide_compositor import _base
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE, FOURIER_BG_CARD
    width = presentation.slide_width.inches - 1.3
    geometries = table_geometries(tuple(item.table.headers), tuple(map(tuple, item.table.rows)), width)
    heading_h = _copy_height(item.title, width, 18) + .04
    condition_h = _copy_height(item.conditions, width, 12) + .04 if item.conditions else 0
    bottom = presentation.slide_height.inches - 1.1 - heading_h - .08 - condition_h
    if item.conditions:
        bottom -= .05
    body_heights = {size: _copy_height(item.text, width, size) + .06 if item.text else 0
                    for size in (BODY_PT, 15, 14)}
    first_slide, top = _base(presentation, title, '')
    first_tops = page_tops(first_slide, top, fit_page_budget)
    layout = comparison_layout(geometries, body_heights, first_tops, first_tops, bottom)
    slides = [first_slide]
    later_tops = first_tops
    if len(layout[3]) > 1:
        # The continuation title can wrap differently. Measure its actual
        # placeholder before choosing the final column widths and page breaks.
        continuation, top = _base(presentation, title + ' (continued)', '')
        slides.append(continuation)
        later_tops = page_tops(continuation, top, fit_page_budget)
        layout = comparison_layout(geometries, body_heights, first_tops, later_tops, bottom)
    geometry, body_pt, spacing, ends = layout
    widths, header_height = geometry.widths, geometry.header_height
    full = '\n'.join(' | '.join(row) for row in [item.table.headers, *item.table.rows])
    start = 0
    for page, end in enumerate(ends):
        if page >= len(slides):
            continuation, _ = _base(presentation, title + ' (continued)', '')
            slides.append(continuation)
        slide = slides[page]
        top = (later_tops if page else first_tops)[spacing]
        body_copy = '' if page else item.text
        body_h = 0 if page else body_heights[body_pt]
        _text(slide, item.title, .65, top, width, heading_h, size=18, bold=True, color=FOURIER_PURPLE).name = 'brief:heading'
        if body_copy:
            _text(slide, body_copy, .65, top + heading_h, width, body_h, size=body_pt, color=FOURIER_DARK).name = 'brief:body'
        table_top = top + heading_h + body_h + .08
        group = item.table.rows[start:end]
        heights = geometry.row_heights[start:end]
        shape = slide.shapes.add_table(len(group) + 1, len(item.table.headers), Inches(.65), Inches(table_top),
                                      Inches(width), Inches(header_height + sum(heights)))
        shape.name = 'brief:comparison_table'
        table = shape.table
        for column, column_width in zip(table.columns, widths):
            column.width = Inches(column_width)
        for offset, row in enumerate([item.table.headers, *group]):
            table.rows[offset].height = Inches(header_height if offset == 0 else heights[offset - 1])
            for column, text in enumerate(row):
                cell = table.cell(offset, column)
                cell.text = text
                cell.margin_left = cell.margin_right = Inches(.09)
                cell.margin_top = cell.margin_bottom = Inches(.06)
                cell.text_frame.word_wrap = True
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(FOURIER_PURPLE if offset == 0 else FOURIER_BG_CARD)
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.font.size = Pt(14)
                    paragraph.font.bold = offset == 0
                    paragraph.font.color.rgb = RGBColor.from_string('FFFFFF' if offset == 0 else FOURIER_DARK)
                    paragraph.line_spacing = Pt(17)
        if item.conditions:
            _text(slide, item.conditions, .65, table_top + header_height + sum(heights) + .05,
                  width, condition_h, size=12, color=FOURIER_MUTED).name = 'brief:conditions'
        _text(slide, _source_footer(item.pages), .55, presentation.slide_height.inches - .82,
              width, .20, size=9, color=FOURIER_MUTED)
        slide.notes_slide.notes_text_frame.text = '\n\n'.join([notes, item.title, item.text, item.conditions, full, _source_footer(item.pages)])
        start = end
    return slides
