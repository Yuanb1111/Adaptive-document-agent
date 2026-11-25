"""Resolve selected table cells to literal, item-owned source line ranges."""
import re
import json

from adaptive_document_agent.services.source_quotes import normalize_quote
from .source_phrase_ranges import PHRASE_PATTERN, adjacent_clause_cell, numbered_page_text, phrase_coordinates


SOURCE_CELL_INSTRUCTIONS = (
    'A complete condition can span adjacent offered clauses. You may combine their first start '
    'and last end into one @phrase[page:start-end] cell if the clauses are consecutive on the same '
    'page, belong to one sentence and fit 180 characters. Read the complete source behind each '
    'reference. Keep a negation or restriction with its predicate and pair it with the subject it governs. '
)


def phrase_cell_options(page, text):
    """Offer continuous clauses across PDF line wraps; never derive or join facts."""
    cuts = [0]
    for match in re.finditer(r'[,;，；。！？]|[.!?](?=\s|$)', text):
        if match[0] == ',' and text[:match.start()].rstrip()[-1:].isdigit() and text[match.end():].lstrip()[:1].isdigit():
            continue  # Preserve numerical groups and complete date tokens.
        cuts.append(match.end())
    cuts.append(len(text))
    spans = []
    connectors = re.compile(r'\b(?:that|nor|with respect to|with a view to|with an aggregate|within|'
                            r'to keep|including|as well as|as indicated by|which)\b', re.I)
    for begin, finish in zip(cuts, cuts[1:]):
        start = begin
        while start < finish:
            while start < finish and text[start].isspace():
                start += 1
            end = finish
            while end > start and text[end - 1].isspace():
                end -= 1
            if start == end:
                break
            if len(' '.join(text[start:end].split())) > 180:
                boundaries = [start + m.start() for m in connectors.finditer(text[start:end])
                              if m.start() > 0]
                choices = [cut for cut in boundaries if 12 <= len(' '.join(text[start:cut].split())) <= 160]
                if not choices:
                    choices = [start + m.start() for m in re.finditer(r'\s+', text[start:end])
                               if 12 <= len(' '.join(text[start:start + m.start()].split())) <= 160]
                if not choices:
                    break  # An unsplittable source token cannot become a cell.
                end = max(choices)
            spans.append((start, end))
            start = end
    options, seen = [], set()
    for start, end in spans:
        literal = ' '.join(text[start:end].split())
        if 8 <= len(literal) <= 180 and (start, end) not in seen:
            seen.add((start, end))
            options.append(dict(ref=f'@phrase[{page}:{start}-{end}]', characters=len(literal), text=literal))
    return options


def source_cell_item_schema(messages):
    """Validate menu references and fitting whole-clause spans without enumerating all combinations."""
    from typing import Annotated, Literal
    from pydantic import BaseModel, BeforeValidator, Field, TypeAdapter, create_model, model_validator
    from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem, BriefComparisonTable
    refs, pages, spans = set(), {}, {}
    for message in messages:
        content = message.get('content', '')
        if not isinstance(content, str) or not content.startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n'):
            continue
        try:
            value = json.loads(content.split('\n', 1)[1].rsplit('\n', 1)[0])
            for page in value.get('source_pages', []):
                offered = [option['ref'] for option in page.get('table_cell_reference_options', [])]
                refs.update(offered)
                if offered and page.get('lines'):
                    number = page['page']
                    pages[number] = numbered_page_text(page)
                    spans[number] = {phrase_coordinates(ref)[1:] for ref in offered}
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    if not refs:
        return ExecutiveBriefItem
    cell = Literal[tuple(sorted(refs))]
    if pages:
        menu = TypeAdapter(cell)
        def validate_reference(value):
            if isinstance(value, str) and value not in refs:
                try:
                    return adjacent_clause_cell(value, pages, spans)
                except ValueError:
                    pass
            return menu.validate_python(value)  # Keep exact menu errors in targeted format repairs.
        wire = cell | Annotated[str, Field(pattern=PHRASE_PATTERN)]
        cell = Annotated[str, BeforeValidator(validate_reference, json_schema_input_type=wire)]
    table = create_model('ReferencedSourceTable', __base__=BriefComparisonTable,
                         rows=(list[list[cell]], ...))
    def plain_item(value):
        return value.model_dump(mode='json') if isinstance(value, BaseModel) else value
    return create_model('ReferencedSourceAddition', __base__=ExecutiveBriefItem,
                        __validators__={'plain_item': model_validator(mode='before')(plain_item)},
                        comparison_table=(table | None, None))


def table_cell_options(page, text):
    lines = text.splitlines()
    options = []
    for first, line in enumerate(lines, 1):
        if not line.strip():
            continue
        for last in range(first, min(first + 1, len(lines)) + 1):
            literal = ' '.join(' '.join(lines[first - 1:last]).split())
            if 1 <= len(literal) <= 180:
                options.append(dict(ref=f'@cell[{page}:{first}-{last}]', characters=len(literal)))
    return options


def _bind_selected_phrase_evidence(item, page, first, last, source):
    """Restore context for an explicitly selected source phrase within quote capacity."""
    from .source_integration_quotes import _literal_parts
    from adaptive_document_agent.models.executive_brief import BriefQuote, BRIEF_EVIDENCE_LIMIT
    if not any(q.page == page and normalize_quote(q.text)
               and normalize_quote(q.text) in normalize_quote(source) for q in item.evidence):
        return False
    ref = f'@phrase[{page}:{first}-{last}]'
    offered = {o['ref'] for o in phrase_cell_options(page, source)}
    if ref not in offered:
        try:
            adjacent_clause_cell(ref, {page: source}, {page: {phrase_coordinates(r)[1:] for r in offered}})
        except ValueError:
            return False
    separators = list(re.finditer(r'\n\s*\n', source))
    start = max((m.end() for m in separators if m.end() <= first), default=0)
    end = min((m.start() for m in separators if m.start() >= last), default=len(source))
    literal = source[start:end].strip()
    normalized = normalize_quote(literal)
    retained = [q for q in item.evidence if q.page != page or normalize_quote(q.text) not in normalized]
    parts = _literal_parts(literal, BRIEF_EVIDENCE_LIMIT - len(retained))
    if parts is None:
        return False
    item.evidence = [*retained, *(BriefQuote(page=page, text=part) for part in parts)]
    return True


def bind_table_cells(item, pages, *, selected_phrase_evidence=False):
    from adaptive_document_agent.services.source_quotes import continuous_quote_passages
    table = getattr(item, 'comparison_table', None)
    if table is None:
        return
    rows = []
    for row in table.rows:
        cells = []
        for cell in row:
            phrase = re.fullmatch(r'@phrase\[(\d+):(\d+)-(\d+)\]', cell)
            match = re.fullmatch(r'@cell\[(\d+):(\d+)-(\d+)\]', cell)
            if not match and not phrase:
                if cell.startswith(('@cell[', '@phrase[')):
                    raise ValueError('Invalid literal table cell reference.')
                cells.append(cell)  # Legacy literal cells still pass the source validator.
                continue
            page, first, last = map(int, (phrase or match).groups())
            source = pages.get(page, '')
            if phrase:
                if not 0 <= first < last <= len(source):
                    raise ValueError(f'Invalid table cell range {cell}.')
                literal = ' '.join(source[first:last].split())
            else:
                lines = source.splitlines()
                if not 1 <= first <= last <= len(lines):
                    raise ValueError(f'Invalid table cell range {cell}.')
                literal = ' '.join(' '.join(lines[first - 1:last]).split())
            passages = continuous_quote_passages(item.evidence, pages)
            covered = any(
                    q.page == page and normalize_quote(q.text) in normalize_quote(source)
                    and normalize_quote(literal) in normalize_quote(q.text) for q in passages)
            if (not covered and phrase and selected_phrase_evidence and 1 <= len(literal) <= 180
                    and _bind_selected_phrase_evidence(item, page, first, last, source)):
                passages = continuous_quote_passages(item.evidence, pages)
                covered = any(q.page == page and normalize_quote(literal) in normalize_quote(q.text)
                              for q in passages)
            if not 1 <= len(literal) <= 180 or not covered:
                raise ValueError(f'Table cell {cell} needs a literal phrase within its own quoted evidence, at most 180 characters.')
            cells.append(literal)
        rows.append(cells)
    item.comparison_table = type(table).model_validate(dict(headers=table.headers, rows=rows))
