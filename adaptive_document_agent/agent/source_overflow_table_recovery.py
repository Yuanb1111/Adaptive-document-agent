"""Restore complete, source-addressed comparison tables after a transport format error."""
import json
import re
from typing import get_args

from pydantic import create_model
from .brief_patch_capacity import complete_patch
from .prompting import untrusted_document_message
from .source_addition_parts import _sentence_spans
from .source_table_cells import source_cell_item_schema


def _coordinates(ref):
    match = re.fullmatch(r'@phrase\[(\d+):(\d+)-(\d+)\]', ref)
    if not match:
        raise ValueError('Expected an original phrase reference.')
    return tuple(map(int, match.groups()))


def _source_directory(messages):
    pages, options = {}, {}
    for message in messages:
        text = message.get('content', '')
        if not text.startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n'):
            continue
        data = json.loads(text.split('\n', 1)[1].rsplit('\n', 1)[0])
        if not isinstance(data, dict):
            continue
        for page in data.get('source_pages', []):
            number, lines = page['page'], []
            crlf = set(page.get('crlf_line_endings', []))
            for i, line in enumerate(page.get('lines', []), 1):
                prefix = f'{i} | '
                if not line.startswith(prefix):
                    raise ValueError('Physical line numbering differs from the supplied page.')
                lines.append(line[len(prefix):] + ('\r\n' if i in crlf else '\n'))
            pages[number] = ''.join(lines)
            options[number] = {_coordinates(o['ref'])[1:] for o in page.get('table_cell_reference_options', [])}
    return pages, options


def _offered_span(ref, owned, pages, options):
    page, start, end = _coordinates(ref)
    if page not in owned or not 0 <= start < end <= len(pages[page]):
        raise ValueError('Phrase is outside its own physical source.')
    # Accept a compound selection only if its endpoints cover a complete
    # sequence of offered phrases, with physical whitespace between them.
    source = pages[page]
    position = start
    for a, b in sorted(options[page]):
        if a < start or b > end:
            continue
        if position > a or source[position:a].strip():
            break
        position = b
    if position != end or not any(a == start for a, _ in options[page]):
        raise ValueError('Phrase endpoints are not supported by the source menu.')
    return page, start, end


def _word_key(text):
    return ' ' + ' '.join(w for w in re.findall(r'\w+', text.casefold()) if w != 'the') + ' '


def _restore_table(table, owned, pages, options, authored):
    if not isinstance(table, dict) or set(table) != {'headers', 'rows'}:
        raise ValueError('Incomplete source table.')
    headers, rows = table['headers'], table['rows']
    if not isinstance(headers, list) or not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('Invalid source table dimensions.')
    widths = {len(row) for row in rows if isinstance(row, list)}
    if not widths or not 2 <= min(widths) <= max(widths) <= len(headers) <= 4:
        raise ValueError('Source table requires complete comparable columns.')
    width = min(widths)
    if max(widths) != len(headers):
        raise ValueError('A full authored row must establish the selected column headings.')
    if width != len(headers):
        # All original headers remain visible. A wider row's last two cells
        # can occupy one display cell only if physically adjacent below.
        headers = [*headers[:width-1], ' / '.join(headers[width-1:])]
    refs, result = set(), []
    for row in rows:
        if not isinstance(row, list):
            raise ValueError('Invalid source row.')
        cells = [_offered_span(ref, owned, pages, options) for ref in row]
        if len(cells) > width:
            tail = cells[width-1:]
            for (p, _, end), (q, start, _) in zip(tail, tail[1:]):
                if p != q or start < end or pages[p][end:start].strip():
                    raise ValueError('Cannot join separated source cells in a comparison.')
            cells = [*cells[:width-1], (tail[0][0], tail[0][1], tail[-1][2])]
        output = []
        for i, (page, start, end) in enumerate(cells):
            source = pages[page]
            if i and cells[i-1][0] == page and cells[i-1][2] < start:
                gap_start = cells[i-1][2]
                gap = source[gap_start:start]
                # Restore a skipped connective/qualification only when it is
                # already present in this item's own model-authored wording.
                gap_key = _word_key(gap)
                if gap_key.strip() and any(gap_key in _word_key(text) for text in authored):
                    left = gap_start + len(gap) - len(gap.lstrip())
                    if len(' '.join(source[left:end].split())) <= 180:
                        start = left
            if not 1 <= len(' '.join(source[start:end].split())) <= 180:
                raise ValueError('A reconstructed literal cell exceeds audience capacity.')
            ref = f'@phrase[{page}:{start}-{end}]'
            output.append(ref)
            refs.add(ref)
        result.append(output)
    return dict(headers=headers, rows=result), refs


def recover_overflow_tables(error, messages, schema, repair, originals, reviewed_text, entry):
    raw = complete_patch(error, repair.model_fields)
    pages, options = _source_directory(messages)
    fields, revised, verified = {}, dict(originals), {}
    for key, candidate in raw.items():
        expected = set(repair.model_fields[key].annotation.model_fields)
        if not isinstance(candidate, dict) or not expected <= candidate.keys() or 'comparison_table' not in expected:
            raise ValueError('Missing author-selected table or required fields.')
        for name in set(candidate) - expected:
            if name not in {'label', 'evidence'} or candidate[name] != originals[key].get(name):
                raise ValueError('An unrequested item field was changed.')
        text = candidate['text']
        if not isinstance(text, str) or not 0 < len(text) <= 550:
            raise ValueError('The submitted table needs its own complete fitting body.')
        owning_pages = {q['page'] for q in originals[key]['evidence']}
        authors = [originals[key]['text'], reviewed_text[key], text]
        table, refs = _restore_table(candidate['comparison_table'], owning_pages, pages, options, authors)
        if table['headers'] != candidate['comparison_table']['headers']:
            # Keep the substantive correction's complete introductory sentence
            # alongside the condensed table body when both fit. It supplies the
            # scope of the following comparisons without editing either draft.
            start, end = next(_sentence_spans(authors[0]))
            introduction = authors[0][start:end]
            if introduction not in text:
                text = introduction + ' ' + text
        local_menu = dict(source_pages=[dict(table_cell_reference_options=[dict(ref=ref) for ref in sorted(refs)])])
        table_item = source_cell_item_schema([untrusted_document_message(json.dumps(local_menu))])
        table_type = next(t for t in get_args(table_item.model_fields['comparison_table'].annotation)
                          if t is not type(None))
        original_type = schema.model_fields[key].annotation
        fields[key] = (create_model('RestoredSourceComparisonItem', __base__=original_type,
                                    comparison_table=(table_type, ...)), ...)
        revised[key] = {**originals[key], **{n: candidate[n] for n in expected}, 'text': text,
                        'comparison_table': table}
        verified[key] = dict(submitted=candidate['comparison_table'], restored=table, body=text)
    restored = create_model('RestoredReopenedSourceTables', __base__=schema, **fields).model_validate(revised)
    entry['recovered_source_overflow_tables'] = verified
    return restored
