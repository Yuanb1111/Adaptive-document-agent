"""One bounded semantic re-read of rejected spans, retaining accepted evidence."""
import json
from concurrent.futures import CancelledError

from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.summary_validation import reading_errors
from .prompting import untrusted_document_message
from .summary_read_binding import bind_reading, line_coverage, missing_ranges, reconcile_layout


_COVERAGE = {'Summary parts skip or overlap supplied source lines',
             'Summary block was not completely read and assigned'}


def repair_rejected_parts(gateway, result, blocks, parts, response, previous,
                          source_messages, cancelled, audit):
    from .summary_reader import SummaryReadBatch
    coverage = line_coverage(parts, blocks)
    # Real overlapping spans can be repartitioned by the model. Unknown source
    # IDs and out-of-block endpoints still have no trustworthy repair scope.
    if (any(row['outside_lines'] for row in coverage)
            or any(p.block_id not in {b.id for b in blocks} for p in response.parts)):
        return None

    def probe(items):
        return SummaryReview(document_id=result.document.document_id,
            document_sha256=result.document.sha256, source_pages=sorted({b.page for b in blocks}),
            source_blocks=blocks, parts=items)

    overlap = {row['block_id']: set(row['overlap_lines']) for row in coverage}
    gap_coverage = [dict(row, overlap_lines=[]) for row in coverage]
    rejected, ranges = [], missing_ranges(gap_coverage)
    lengths = {b.id: len(b.text.splitlines(keepends=True)) for b in blocks}
    raw_parts = {(p.block_id, p.start_line, p.end_line): p for p in response.parts}
    for part in parts:
        raw = raw_parts.get((part.block_id, part.start_line, part.end_line))
        binding_errors = []
        if raw is not None:
            _, binding_errors = bind_reading(SummaryReadBatch(parts=[raw]), blocks, result, {},
                                             literal_fallback=True)
        errors = binding_errors + [e for e in reading_errors(probe([part]), result,
                                    complete_scope=False) if e not in _COVERAGE]
        if any(part.start_line <= line <= part.end_line for line in overlap.get(part.block_id, ())):
            errors.append('Repartition overlapping content so every source line belongs to exactly one part')
        if not errors:
            continue
        span = dict(block_id=part.block_id, start_line=part.start_line, end_line=part.end_line)
        rejected.append({**span, 'errors': list(dict.fromkeys(errors)),
                         'previous_part': raw.model_dump() if raw else part.model_dump()})
        # A rejected table quote may identify a real header in a neighbouring
        # part. Permit repartitioning those literal lines, never borrowed units.
        for fact in raw.facts if raw else []:
            if 1 <= fact.quote_start_line <= fact.quote_end_line <= lengths[part.block_id]:
                span['start_line'] = min(span['start_line'], fact.quote_start_line)
                span['end_line'] = max(span['end_line'], fact.quote_end_line)
        ranges.append(span)
    if not rejected:
        return None
    ranges = _whole_part_ranges(ranges, parts)
    replaced = [p for p in parts if any(_intersects(p.block_id, p.start_line, p.end_line, r) for r in ranges)]
    retained = [p for p in parts if p not in replaced]
    record = {'ranges': ranges, 'rejected_parts': rejected,
              'repartitioned_part_ids': [p.id for p in replaced]}
    audit['rejected_part_read'] = record
    try:
        if cancelled.is_set():
            raise CancelledError('Summary reading cancelled')
        replacement = gateway.generate_structured([
            *source_messages,
            untrusted_document_message(json.dumps(record, ensure_ascii=False)),
            {'role': 'user', 'content':
             'Re-read ONLY the listed inclusive ranges. Original blocks are context. Partition those '
             'ranges exactly once; do not return any lines outside them. Some ranges include adjacent '
             'parts so a table and its headers can be grouped together without borrowing evidence. '
             'Retain all their substantive content. Correct the specific '
             'errors in rejected_parts. Classify meaning from the original source, not the previous '
             'classification. Diagram components and relationships are substantive content, not '
             'layout merely because they are fragmented labels. Qualitative facts need no numbers. '
             'For lead-ins, state only what is introduced; never invent the following details. '
             'Every content part needs source-supported facts, with quotes entirely inside its '
             'assigned range. If a table cannot be paraphrased safely, use its exact source wording '
             'including the quoted headers as internal fact text; the slide editor rewrites later. '
             'Do not hide substance as headings/layout to pass validation.'}],
            SummaryReadBatch, stage='presentation', allow_repair=False, cancelled=cancelled)
        record['response'] = replacement.model_dump(mode='json')
        if any(not any(p.block_id == r['block_id'] and
                       r['start_line'] <= p.start_line <= p.end_line <= r['end_line']
                       for r in ranges) for p in replacement.parts):
            raise ValueError('Summary targeted reading changed already accepted source lines')
        additions, errors = bind_reading(replacement, blocks, result, record,
                                        literal_fallback=True, recover_cross_part=True)
        combined = reconcile_layout(retained + additions, blocks, record)
        errors += reading_errors(probe(combined), result, complete_scope=False)
        record['errors'] = errors
        record['line_coverage'] = line_coverage(combined, blocks)
        if errors:
            raise ValueError('; '.join(errors))
        order = {b.id: i for i, b in enumerate(blocks)}
        return sorted(combined, key=lambda p: (order[p.block_id], p.start_line))
    except Exception as exc:
        record['error'] = str(exc)
        if isinstance(exc, LLMStructuredOutputError):
            record['raw_response'] = exc.response.text
        if isinstance(exc, ValueError):
            raise ValueError('; '.join(previous['errors']) + '; targeted reading: ' + str(exc)) from exc
        raise


def _intersects(block_id, start, end, span):
    return block_id == span['block_id'] and start <= span['end_line'] and end >= span['start_line']


def _whole_part_ranges(ranges, parts):
    """Expand only intersected ownership spans; merge overlapping repair scopes."""
    ranges = [dict(r) for r in ranges]
    for span in ranges:
        changed = True
        while changed:
            before = span['start_line'], span['end_line']
            for part in parts:
                if _intersects(part.block_id, part.start_line, part.end_line, span):
                    span['start_line'] = min(span['start_line'], part.start_line)
                    span['end_line'] = max(span['end_line'], part.end_line)
            changed = before != (span['start_line'], span['end_line'])
    merged = []
    for span in sorted(ranges, key=lambda r: (r['block_id'], r['start_line'])):
        if merged and _intersects(span['block_id'], span['start_line'], span['end_line'], merged[-1]):
            merged[-1]['end_line'] = max(merged[-1]['end_line'], span['end_line'])
        else:
            merged.append(span)
    return merged
