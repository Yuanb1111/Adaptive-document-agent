"""Resolve physical source ranges selected from numbered pages and their phrase menus."""
import re


PHRASE_PATTERN = r'^@phrase\[([0-9]{1,8}):([0-9]{1,9})-([0-9]{1,9})\]$'


def phrase_coordinates(reference):
    match = re.fullmatch(PHRASE_PATTERN, reference)
    if not match:
        raise ValueError('Expected an original phrase reference.')
    return tuple(map(int, match.groups()))


def numbered_page_text(page):
    lines = []
    crlf = set(page.get('crlf_line_endings', []))
    for i, line in enumerate(page.get('lines', []), 1):
        prefix = f'{i} | '
        if not line.startswith(prefix):
            raise ValueError('Physical line numbering differs from the supplied page.')
        lines.append(line[len(prefix):] + ('\r\n' if i in crlf else '\n'))
    return ''.join(lines)


def offered_phrase_span(ref, owned, pages, options):
    page, start, end = phrase_coordinates(ref)
    if page not in owned or not 0 <= start < end <= len(pages[page]):
        raise ValueError('Phrase is outside its own physical source.')
    position = start
    for a, b in sorted(options[page]):
        if a < start or b > end:
            continue
        if position > a or pages[page][position:a].strip():
            break
        position = b
    if position != end or not any(a == start for a, _ in options[page]):
        raise ValueError('Phrase endpoints are not supported by the source menu.')
    return page, start, end


def adjacent_clause_cell(ref, pages, options):
    """A single quoted cell can retain successive clauses from one sentence."""
    page, start, end = offered_phrase_span(ref, pages, pages, options)
    literal = ' '.join(pages[page][start:end].split())
    if len(literal) > 180 or re.search(r'[.!?](?=\s)|[。！？](?!$)', literal):
        raise ValueError('Adjacent source clauses must fit one cell in the same sentence.')
    return ref
