"""Fold very short text pages into existing pages without manufacturing copy."""

from .text_capacity import wrap_copy


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


def _sparse(slide):
    bodies = _bodies(slide)
    if not bodies:
        return False
    # Charts, tables, source pictures, and other evidence are substantive even
    # when the accompanying prose is short. Never count them as empty space.
    if any(s.has_chart or s.has_table or s.shape_type in (6, 13) for s in slide.shapes):
        return False
    headings = [s for s in slide.shapes if s.name == 'brief:heading' and s.text.strip()]
    body_lines = sum(len(wrap_copy(s.text, s.width.inches, 16)) for s in bodies)
    heading_lines = sum(len(wrap_copy(s.text, s.width.inches, 18)) for s in headings)
    # An independently rendered definition/caveat is additional content, not
    # whitespace. Leave such pages intact rather than dropping untracked copy.
    if any(s.has_text_frame and s.text.strip() and s.top.inches >= 1.45
           and not s.is_placeholder and s.name not in {'brief:body', 'brief:heading', 'closing:body'}
           and not s.text.startswith('Source:') for s in slide.shapes):
        return False
    return body_lines <= 2 and body_lines + heading_lines <= 4


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
    sparse = [s for s in slides if _sparse(s)]
    targets = [s for s in slides if s not in sparse and (
        _bodies(s) or any(shape.has_chart or shape.has_table for shape in s.shapes))]
    if not targets:
        return []
    omitted = []
    for slide in sparse:
        title = _title(slide)
        copy = '\n'.join(s.text for s in slide.shapes if s.has_text_frame and s.text.strip()
                         and (s.name in {'brief:heading', 'brief:body', 'closing:body'}
                              or (s.text.startswith('Source:')
                                  and 'page references not available' not in s.text)))
        text = f'{title}: {copy}' if title else copy
        ordered = sorted(targets, key=lambda s: (
            _title(s).removesuffix(' (continued)') != title.removesuffix(' (continued)'),
            abs(slides.index(s) - slides.index(slide))))
        target = ordered[0]
        width = presentation.slide_width.inches - 1.1
        height = len(wrap_copy(text, width - .1, 11)) * 14 / 72 + .12
        for candidate in ordered:
            occupied = [s for s in candidate.shapes if s.top.inches >= 1
                        and s.top.inches < presentation.slide_height.inches - 1.02
                        and (s.has_chart or s.has_table or s.shape_type in (6, 13)
                             or (s.has_text_frame and s.text.strip()))]
            top = max((s.top.inches + s.height.inches for s in occupied), default=1.5) + .12
            if top + height <= presentation.slide_height.inches - 1.02:
                _text(candidate, text, .55, top, width, height, size=11,
                      color=FOURIER_MUTED).name = 'sparse:retained_note'
                target = candidate
                break
        target.notes_slide.notes_text_frame.text += (
            '\n\nMerged short page:\n' + text + '\n' + slide.notes_slide.notes_text_frame.text)
        destinations[slide.slide_id] = target.slide_id
        slide_id = next(sid for sid in presentation.slides._sldIdLst if sid.id == slide.slide_id)
        presentation.part.drop_rel(slide_id.rId)
        presentation.slides._sldIdLst.remove(slide_id)
        omitted.append(title)

    # Rebuild affected agendas so deleted pages do not leave dangling entries
    # or gaps in their numbering. Other authored section labels stay unchanged.
    labels = lambda s: {_title(s), getattr(s, '_ada_section_label', '')}
    remaining_titles = {label.casefold() for s in presentation.slides for label in labels(s)}
    removed_titles = {label.casefold() for s in sparse for label in labels(s)} - remaining_titles
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
