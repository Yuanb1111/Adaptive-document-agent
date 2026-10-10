"""Fold very short text pages into existing pages without manufacturing copy."""

from .text_capacity import wrap_copy
import json


def _bodies(slide):
    return [s for s in slide.shapes if s.has_text_frame and s.text.strip()
            and s.name in {'brief:body', 'closing:body'}]


def _title(slide):
    # Generated content uses the template's title placeholders.
    for index in (14, 15):
        shape = next((s for s in slide.placeholders if s.placeholder_format.idx == index), None)
        if shape is not None and shape.has_text_frame and shape.text.strip():
            return shape.text.strip()
    return ''


def _sparse(slide, page_height=7.5):
    if any(properties.get('descr', '').startswith('ADA_SUMMARY_ITEM_V2:')
           for shape in slide.shapes for properties in shape.element.xpath('.//p:cNvPr')):
        # Complete introductory coverage cannot be folded into generic notes.
        return False
    bodies = _bodies(slide)
    if not bodies:
        return False
    # Charts, tables, source pictures, and other evidence are substantive even
    # when the accompanying prose is short. Never count them as empty space.
    tables = [s for s in slide.shapes if s.has_table]
    short_closing = (len(tables) == 1 and tables[0].name.startswith('closing:evidence:')
                     and len(tables[0].table.rows) <= 2 and tables[0].height.inches <= 1.4)
    if any(s.has_chart or (s.has_table and not short_closing) or s.shape_type in (6, 13) for s in slide.shapes):
        return False
    headings = [s for s in slide.shapes if s.name in {'brief:heading', 'closing:heading'} and s.text.strip()]
    body_lines = sum(len(wrap_copy(s.text, s.width.inches, 16)) for s in bodies)
    heading_lines = sum(len(wrap_copy(s.text, s.width.inches, 18)) for s in headings)
    # An independently rendered definition/caveat is additional content, not
    # whitespace. Leave such pages intact rather than dropping untracked copy.
    if any(s.has_text_frame and s.text.strip() and s.top.inches >= 1.45
           and not s.is_placeholder and s.name not in {'brief:body', 'brief:heading', 'closing:body', 'closing:heading'}
           and not s.text.startswith('Source:') for s in slide.shapes):
        return False
    if getattr(slide, '_ada_review_status', False):
        return True
    content_height = sum(s.height.inches for s in [*bodies, *headings])
    available = max(.1, page_height - 2.5)
    return (body_lines <= 2 and body_lines + heading_lines <= 4
            or len(bodies) == 1 and content_height / available < .35)


def fold_sparse_text_pages(presentation, result=None):
    """Remove standalone one/two-line brief pages; retain their text and notes.

    Keep short copy visible in an available body-page margin where it fits.
    The complete copy and source references always survive in speaker notes.
    Covers, dividers, visual pages and the closing artwork are not candidates.
    """
    from .pptx_export import _text, FOURIER_MUTED, _render_contents_entries

    slides = list(presentation.slides)
    original_ids = [s.slide_id for s in slides]
    destinations = {identifier: identifier for identifier in original_ids}
    sparse = [s for s in slides if _sparse(s, presentation.slide_height.inches)]
    targets = [s for s in slides if s not in sparse and (
        _bodies(s) or any(shape.has_chart or shape.has_table for shape in s.shapes))]
    if not targets:
        return []
    omitted = []
    for slide in sparse:
        title = _title(slide)
        copy = '\n'.join(s.text for s in slide.shapes if s.has_text_frame and s.text.strip()
                         and (s.name in {'brief:heading', 'brief:body', 'closing:body', 'closing:heading'}
                              or (s.text.startswith('Source:')
                                  and 'page references not available' not in s.text)))
        text = f'{title}: {copy}' if title else copy
        tables = [s for s in slide.shapes if s.has_table]
        table_height = sum(s.height.inches + .12 for s in tables)
        ordered = sorted(targets, key=lambda s: (
            _title(s).removesuffix(' (continued)') != title.removesuffix(' (continued)'),
            abs(slides.index(s) - slides.index(slide))))
        target = ordered[0]
        width = presentation.slide_width.inches - 1.1
        height = len(wrap_copy(text, width - .1, 11)) * 14 / 72 + .12
        placed = False
        for candidate in ordered:
            occupied = [s for s in candidate.shapes if s.top.inches >= 1
                        and s.top.inches < presentation.slide_height.inches - 1.02
                        and (s.has_chart or s.has_table or s.shape_type in (6, 13)
                             or (s.has_text_frame and s.text.strip()))]
            top = max((s.top.inches + s.height.inches for s in occupied), default=1.5) + .12
            if top + height + table_height <= presentation.slide_height.inches - 1.02:
                _text(candidate, text, .55, top, width, height, size=11,
                      color=FOURIER_MUTED).name = 'sparse:retained_note'
                from .evidence_page_packing import _copy_shape
                from pptx.util import Inches
                for table in tables:
                    copied = _copy_shape(candidate, table)
                    copied.top = Inches(top + height + .12)
                    top += table.height.inches + .12
                target = candidate
                placed = True
                break
        if not placed:
            # Notes do not replace audience-visible content. Preserve the
            # original page if its complete copy cannot fit in a target margin.
            continue
        notes = target.notes_slide.notes_text_frame
        merged = {'text': text, 'original_notes': slide.notes_slide.notes_text_frame.text}
        if tables:
            merged['source_tables'] = [[[cell.text for cell in row.cells] for row in table.table.rows]
                                      for table in tables]
        try:
            structured = json.loads(notes.text)
        except (ValueError, TypeError):
            structured = None
        if isinstance(structured, dict):
            structured.setdefault('merged_short_pages', []).append(merged)
            notes.text = json.dumps(structured, ensure_ascii=False, indent=2)
        else:
            notes.text += '\n\nMerged short page:\n' + text + '\n' + merged['original_notes']
            if tables:
                notes.text += '\n\nMerged source tables:\n' + json.dumps(merged['source_tables'], ensure_ascii=False)
        destinations[slide.slide_id] = target.slide_id
        slide_id = next(sid for sid in presentation.slides._sldIdLst if sid.id == slide.slide_id)
        presentation.part.drop_rel(slide_id.rId)
        presentation.slides._sldIdLst.remove(slide_id)
        omitted.append(title)

    # Rebuild affected agendas so deleted pages do not leave dangling entries
    # or gaps in their numbering. Other authored section labels stay unchanged.
    labels = lambda s: {_title(s), getattr(s, '_ada_section_label', '')}
    remaining_titles = {label.casefold() for s in presentation.slides for label in labels(s)}
    retained_parts = {s.part for s in presentation.slides}
    removed_titles = {label.casefold() for s in sparse if s.part not in retained_parts for label in labels(s)} - remaining_titles
    presentation.part.rename_slide_parts([sid.rId for sid in presentation.slides._sldIdLst])
    for slide in list(presentation.slides):
        entries = [s.text for s in slide.shapes if s.name.startswith('contents:entry:')]
        kept = [entry for entry in entries if entry.casefold() not in removed_titles]
        if kept == entries:
            continue
        original_notes = slide.notes_slide.notes_text_frame.text
        ids = presentation.slides._sldIdLst
        old = next(sid for sid in ids if sid.id == slide.slide_id)
        position = list(ids).index(old)
        _render_contents_entries(presentation, kept, 'Presentation structure')
        presentation.slides[-1].notes_slide.notes_text_frame.text += '\n\nPrior agenda:\n' + original_notes
        new = ids[-1]
        destinations[slide.slide_id] = new.id
        ids.remove(new)
        presentation.part.drop_rel(old.rId)
        ids.remove(old)
        ids.insert(position, new)
        presentation.part.rename_slide_parts([sid.rId for sid in ids])
    if result is not None and omitted:
        from .presentation_export_trace import rebase_trace
        numbers = {s.slide_id: i + 1 for i, s in enumerate(presentation.slides)}
        rebase_trace(presentation, result, {
            i + 1: numbers[destinations[identifier]] for i, identifier in enumerate(original_ids)})
    return omitted
