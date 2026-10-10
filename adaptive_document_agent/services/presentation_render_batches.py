"""Bounded local validation of long presentations without dropping source pages."""
import io
import json

from pptx import Presentation

from .presentation_rendering import RenderingError, check_render_input

MAX_SLIDES = 500
BATCH_SLIDES = 100


def render_pages(renderer, payload, directory):
    check_render_input(payload)
    deck = Presentation(io.BytesIO(payload))
    count = len(deck.slides)
    if not 1 <= count <= MAX_SLIDES:
        raise RenderingError(f'Presentation exceeds the {MAX_SLIDES}-slide rendering limit.')
    if count <= 150:
        return renderer.render(payload, directory)
    pages, output_size = [], 0
    for start in range(0, count, BATCH_SLIDES):
        batch = Presentation(io.BytesIO(payload))
        stop = min(count, start + BATCH_SLIDES)
        # Preserve each selected slide and its source relationships. Only the
        # temporary renderer input loses pages outside this contiguous range;
        # the final PPT and its protected package digest remain unchanged.
        for index in range(count-1, -1, -1):
            if start <= index < stop:
                continue
            identifier = batch.slides._sldIdLst[index]
            batch.part.drop_rel(identifier.rId)
            batch.slides._sldIdLst.remove(identifier)
        stream = io.BytesIO()
        batch.save(stream)
        target = directory / f'batch-{start // BATCH_SLIDES + 1}'
        target.mkdir()
        rendered = renderer.render(stream.getvalue(), target)
        if len(rendered) != stop-start:
            raise RenderingError('Local renderer omitted pages from a presentation batch.')
        output_size += sum(len(page.png) + len(json.dumps(page.layout).encode('utf-8')) for page in rendered)
        if output_size > 300_000_000:
            raise RenderingError('Rendered output exceeds the 300 MB validation limit.')
        pages.extend(rendered)
    return pages
