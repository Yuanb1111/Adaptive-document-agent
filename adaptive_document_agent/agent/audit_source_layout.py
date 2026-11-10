"""Source text and retained line positions, without inferred columns or assurance."""
from math import isfinite


LAYOUT_INSTRUCTIONS = (
    'A source page may include layout_lines: each row is [literal text, left x, right x, top y] '
    'in PDF points (x increases rightward, y downward). When layout_rotation is supplied, '
    'the coordinates have been rotated by that angle into reading orientation; their relative '
    'positions and source text are unchanged. Otherwise they are original PDF coordinates. These are retained extraction '
    'coordinates for narrow lines, not interpreted table cells, periods or assurance. '
    'Full-width prose coordinates are omitted; ALL prose and qualifiers remain in the full '
    'page text. Coordinate omission is never evidence of a missing qualifier. Inspect the relative '
    'positions of ALL header tiers, year labels, units, qualifiers and value rows. Whitespace '
    'alignment in flattened page text can shift a qualifier to a neighboring column; use the '
    'original line positions to check ownership and distinguish repeated tables. A qualifier '
    'must belong to the exact table AND period. A blank column does not establish audited '
    'status; the complete literal scope/measure chain is still required. Missing or ambiguous '
    'layout never grants assurance. Keep quotation text literal to the supplied full source page. ')


def audit_source_page(page, *, reading_orientation=False):
    """Show narrow line positions for column reading; retain complete page text."""
    result = dict(page=page.page_number, text=page.text)
    lines = []
    for block in page.text_blocks:
        candidates = block.get('lines', [])
        if not isinstance(candidates, (list, tuple)):
            continue
        for line in candidates:
            if not isinstance(line, dict):
                continue
            text, box = line.get('text'), line.get('bbox')
            if (not isinstance(text, str) or not text.strip()
                    or not isinstance(box, (list, tuple)) or len(box) != 4
                    or any(not isinstance(v, (float, int)) or isinstance(v, bool)
                           or not isfinite(v) for v in box)
                    or box[0] > box[2] or box[1] > box[3]):
                continue
            # Only a compact reading view: full-precision boxes remain in the
            # original document. No period/status association is manufactured.
            if reading_orientation and page.reading_rotation in (90, 180, 270):
                from adaptive_document_agent.extraction.source_geometry import rotate_box
                box = rotate_box(box, 0, 0, page.reading_rotation)
                result['layout_rotation'] = page.reading_rotation
            lines.append([text, round(box[0], 2), round(box[2], 2), round(box[1], 2)])
    if lines:
        # Whole-width prose has no neighboring-column position to disambiguate.
        # Keep the complete text, but avoid repeating it in the spatial aid.
        # This geometric filter never recognizes a word, year or audit status.
        width = max(line[2] for line in lines) - min(line[1] for line in lines)
        narrow = [line for line in lines if line[2] - line[1] <= .75 * width]
        if narrow:
            result['layout_lines'] = narrow
    return result
