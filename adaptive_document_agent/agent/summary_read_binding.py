"""Bind model reading to literal lines and reconcile only mechanical layout."""
from collections import Counter

from adaptive_document_agent.models.summary import SummaryFact, SummaryPart
from adaptive_document_agent.services.summary_validation import fact_errors
from adaptive_document_agent.utils.ids import stable_id


def bind_reading(response, blocks, result, record, *, literal_fallback=False):
    by_id = {b.id: b for b in blocks}
    parts, errors = [], []
    for part in response.parts:
        block = by_id.get(part.block_id)
        if block is None:
            errors.append('Summary reader cites an unknown source block')
            continue
        lines = block.text.splitlines(keepends=True)
        source = ''.join(lines[part.start_line-1:part.end_line])
        facts = []
        for fact in part.facts:
            if not part.start_line <= fact.quote_start_line <= fact.quote_end_line <= part.end_line <= len(lines):
                errors.append('Summary fact source span is outside its assigned part')
                continue
            try:
                bound = SummaryFact(label=fact.label, text=fact.text,
                    source_quote=''.join(lines[fact.quote_start_line-1:fact.quote_end_line]).strip(),
                    source_pages=[block.page])
                failures = fact_errors(bound, result, source, block.page, literal_reading=True)
                if failures and literal_fallback:
                    # This is internal evidence capture, never published slide copy.
                    record.setdefault('literal_extracts', []).append({
                        'block_id': block.id, 'start_line': fact.quote_start_line,
                        'end_line': fact.quote_end_line, 'rejected_paraphrase': fact.text,
                        'errors': failures})
                    bound = bound.model_copy(update={'text': bound.source_quote})
                facts.append(bound)
            except ValueError as exc:
                errors.append('Invalid Summary fact source span: ' + str(exc))
        parts.append(SummaryPart(**part.model_dump(exclude={'facts'}), facts=facts,
            id=stable_id('summary_part', block.id, part.start_line, part.end_line),
            source_page=block.page, source_text=source))
    return parts, errors


def line_coverage(parts, blocks):
    """Report exact source gaps and overlaps without interpreting their meaning."""
    details = []
    for block in blocks:
        lines = block.text.splitlines(keepends=True)
        counts = _counts(parts, block.id, len(lines))
        details.append({'block_id': block.id, 'page': block.page,
            'missing_lines': [i for i in range(1, len(lines)+1) if not counts[i]],
            'overlap_lines': [i for i in range(1, len(lines)+1) if counts[i] > 1],
            'outside_lines': sorted({i for p in parts if p.block_id == block.id
                                    for i in (p.start_line, p.end_line) if not 1 <= i <= len(lines)})})
    return details


def reconcile_layout(parts, blocks, record):
    """Keep substantive spans intact; account for whitespace and redundant layout.

    Nonblank missing lines are never inferred to be headings or page numbers.
    A layout-only duplicate can be removed only when all of its lines already
    belong to other parts. Raw model responses stay in the enclosing audit.
    """
    parts = list(parts)
    changes = []
    for block in blocks:
        lines = block.text.splitlines(keepends=True)
        counts = _counts(parts, block.id, len(lines))
        retained = []
        for part in parts:
            if (part.block_id == block.id and part.role == 'layout' and not part.facts
                    and 1 <= part.start_line <= part.end_line <= len(lines)
                    and all(counts[i] > 1 for i in range(part.start_line, part.end_line+1))):
                counts.subtract(range(part.start_line, part.end_line+1))
                changes.append({'action': 'remove_redundant_layout', 'part_id': part.id,
                                'block_id': block.id, 'start_line': part.start_line, 'end_line': part.end_line})
            else:
                retained.append(part)
        parts = retained
        cursor = 1
        while cursor <= len(lines):
            if counts[cursor] or lines[cursor-1].strip():
                cursor += 1
                continue
            start = cursor
            while cursor <= len(lines) and not counts[cursor] and not lines[cursor-1].strip():
                cursor += 1
            end = cursor-1
            parts.append(SummaryPart(id=stable_id('summary_part', block.id, start, end),
                block_id=block.id, start_line=start, end_line=end, source_page=block.page,
                source_text=''.join(lines[start-1:end]), title='Blank layout', role='layout',
                reading_note='Only whitespace occurs in these literal source lines.'))
            changes.append({'action': 'assign_blank_lines', 'block_id': block.id,
                            'start_line': start, 'end_line': end})
    if changes:
        record['layout_reconciliation'] = changes
    return parts


def _counts(parts, block_id, length):
    # Invalid model endpoints remain validation errors, but cannot allocate a
    # counter proportional to an arbitrarily large out-of-source line number.
    return Counter(i for p in parts if p.block_id == block_id
                   for i in range(max(1, p.start_line), min(length, p.end_line)+1))


def missing_ranges(coverage):
    ranges = []
    if any(row['overlap_lines'] or row['outside_lines'] for row in coverage):
        return []
    for row in coverage:
        for number in row['missing_lines']:
            if ranges and ranges[-1]['block_id'] == row['block_id'] and ranges[-1]['end_line'] == number-1:
                ranges[-1]['end_line'] = number
            else:
                ranges.append({'block_id': row['block_id'], 'start_line': number, 'end_line': number})
    return ranges
