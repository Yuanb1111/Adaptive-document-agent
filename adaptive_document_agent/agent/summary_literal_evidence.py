"""Quarantine rejected model copy while retaining only literal owned evidence."""
from adaptive_document_agent.models.summary import SummaryFact
from adaptive_document_agent.services.source_quotes import split_literal_quote
from adaptive_document_agent.services.summary_validation import annotation_numbers


def literal_facts(source, page):
    """No semantic assertions: these chunks require later model-authored copy."""
    return [SummaryFact(label='Source passage', text=quote, source_quote=quote,
                        source_pages=[page], evidence_only=True)
            for quote in split_literal_quote(source.strip(), limit=6000)]


def quarantine_annotation(part, block, record):
    unsupported = annotation_numbers(part, block)
    if not unsupported:
        return part
    record.setdefault('quarantined_annotations', []).append({
        'block_id': block.id, 'start_line': part.start_line, 'end_line': part.end_line,
        'title': part.title, 'reading_note': part.reading_note,
        'unsupported_tokens': sorted(unsupported)})
    return part.model_copy(update={'title': 'Source passage', 'reading_note':
        'The model annotation was withheld after validation; interpret the retained source evidence.'})


def terminal_layout_endpoint(part, block, record):
    """One-past-end layout spans can retain every real line without guessing text."""
    length = len(block.text.splitlines(keepends=True))
    if (part.role != 'layout' or part.facts or not 1 <= part.start_line <= length
            or part.end_line != length + 1):
        return part
    record.setdefault('layout_endpoints', []).append({'block_id': block.id,
        'start_line': part.start_line, 'original_end_line': part.end_line, 'end_line': length})
    return part.model_copy(update={'end_line': length})


def preserve_terminal_page_marker(part, block, lines, source, result, record):
    """Keep a fact-free, mechanically proved footer at its exact source coordinates."""
    if (part.role != 'content' or part.facts or not source.strip()
            or not 1 <= part.start_line <= part.end_line <= len(lines)):
        return part
    page = next((p for p in result.document.pages if p.page_number == block.page), None)
    span_end = block.char_start + sum(len(line) for line in lines[:part.end_line])
    span_start = span_end - len(source)
    if page is None or page.text[span_start:span_end] != source or page.text[span_end:].strip():
        return part

    from adaptive_document_agent.services.summary_layout_evidence import layout_line_evidence
    nonblank = [line for line in layout_line_evidence(source, block.page, result) if line['text'].strip()]
    if len(nonblank) != 1 or nonblank[0]['basis'] != 'literal_terminal_page_marker':
        return part
    record.setdefault('terminal_page_markers', []).append({
        'block_id': block.id, 'start_line': part.start_line, 'end_line': part.end_line,
        'original_part': part.model_dump(mode='json'), 'proof': nonblank[0],
    })
    return part.model_copy(update={'role': 'layout', 'title': 'Page marker',
                                  'reading_note': 'This literal source range contains the printed page marker.'})
