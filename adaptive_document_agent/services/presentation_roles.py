"""Durable native roles survive audience-copy translation and save/reload."""

CLOSING_TITLE = 'ada:closing_title'


def is_closing_slide(slide):
    if any(shape.name == CLOSING_TITLE for shape in slide.shapes):
        return True
    # Compatibility with decks generated before durable roles were introduced.
    layout = getattr(getattr(slide, 'slide_layout', None), 'name', '')
    text = ' '.join(s.text for s in slide.shapes if s.has_text_frame).strip().casefold()
    return 'thank' in layout.casefold() or text == 'thank you'
