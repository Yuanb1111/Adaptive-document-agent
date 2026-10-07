"""Readable editable tables for model-authored literal source comparisons."""
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from .presentation_brief import BODY_PT, _copy_height


def render_comparison(presentation, title, item, *, notes=''):
    """Paginate whole rows; repeat qualifications and source pages on every page."""
    from .slide_compositor import _base
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE, FOURIER_BG_CARD
    from .text_capacity import wrap_copy
    remaining = list(item.table.rows)
    slides = []
    width = presentation.slide_width.inches - 1.3
    col_width = width / len(item.table.headers)
    header_height = max(.45, max(len(wrap_copy(cell, col_width - .18, 14)) for cell in item.table.headers) * 18 / 72 + .14)
    full = '\n'.join(' | '.join(row) for row in [item.table.headers, *item.table.rows])
    while remaining:
        slide, top = _base(presentation, title + (' (continued)' if slides else ''), '')
        heading_h = _copy_height(item.title, width, 18) + .08
        body_h = _copy_height(item.text, width, BODY_PT) + .12
        _text(slide, item.title, .65, top, width, heading_h, size=18, bold=True, color=FOURIER_PURPLE).name = 'brief:heading'
        _text(slide, item.text, .65, top + heading_h, width, body_h, size=BODY_PT, color=FOURIER_DARK).name = 'brief:body'
        table_top = top + heading_h + body_h + .14
        capacity = presentation.slide_height.inches - 1.1 - table_top
        group, heights = [], []
        for row in remaining:
            height = max(.45, max(len(wrap_copy(cell, col_width - .18, 14)) for cell in row) * 18 / 72 + .14)
            if header_height + sum(heights) + height > capacity:
                break
            group.append(row)
            heights.append(height)
        if not group:
            raise ValueError('Brief comparison row and qualifications exceed readable page capacity.')
        shape = slide.shapes.add_table(len(group) + 1, len(item.table.headers), Inches(.65), Inches(table_top),
                                      Inches(width), Inches(header_height + sum(heights)))
        shape.name = 'brief:comparison_table'
        table = shape.table
        for offset, row in enumerate([item.table.headers, *group]):
            table.rows[offset].height = Inches(header_height if offset == 0 else heights[offset - 1])
            for column, text in enumerate(row):
                cell = table.cell(offset, column)
                cell.text = text
                cell.margin_left = cell.margin_right = Inches(.09)
                cell.margin_top = cell.margin_bottom = Inches(.06)
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(FOURIER_PURPLE if offset == 0 else FOURIER_BG_CARD)
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.font.size = Pt(14)
                    paragraph.font.bold = offset == 0
                    paragraph.font.color.rgb = RGBColor.from_string('FFFFFF' if offset == 0 else FOURIER_DARK)
                    paragraph.line_spacing = Pt(18)
        _text(slide, _source_footer(item.pages), .55, presentation.slide_height.inches - .82,
              width, .20, size=9, color=FOURIER_MUTED)
        slide.notes_slide.notes_text_frame.text = '\n\n'.join([notes, item.title, item.text, full, _source_footer(item.pages)])
        slides.append(slide)
        remaining = remaining[len(group):]
    return slides
