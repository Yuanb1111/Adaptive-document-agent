"""Bounded semantic re-reads of rejected spans, retaining accepted evidence."""
import json
from concurrent.futures import CancelledError

from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.summary_validation import reading_errors
from .prompting import untrusted_document_message
from .summary_read_binding import bind_reading, line_coverage, missing_ranges, reconcile_layout
from .summary_read_request import reading_request


_COVERAGE = {'Summary parts skip or overlap supplied source lines',
             'Summary block was not completely read and assigned'}
_LAYOUT_ERRORS = {'Layout-only classification cannot hide a substantive source passage',
                  'Nonblank layout needs source header/footer evidence; re-read this range for substantive content'}


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
    feedback = _layout_feedback(replaced, result)
    if feedback:
        record['layout_evidence'] = feedback
    audit['rejected_part_read'] = record
    try:
        current = record
        for targeted_attempt in range(2):
            if cancelled.is_set():
                raise CancelledError('Summary reading cancelled')
            replacement = reading_request(gateway, [
                *source_messages,
                untrusted_document_message(json.dumps(current, ensure_ascii=False)),
                {'role': 'user', 'content':
                 'Re-read ONLY the listed inclusive ranges. Original blocks are context. Partition those '
                 'ranges exactly once; do not return any lines outside them. Some ranges include adjacent '
                 'parts so a table and its headers can be grouped together without borrowing evidence. '
                 'Retain all their substantive content. Correct the specific '
                 'errors in rejected_parts. Classify meaning from the original source, not the previous '
                 'classification. Diagram components and relationships are substantive content, not '
                 'layout merely because they are fragmented labels. Qualitative facts need no numbers. '
                 'For lead-ins and source cross-references, retain what is introduced or referenced; '
                 'never invent the following details. layout_evidence lists exact source lines and '
                 'their mechanical proofs: one proved footer cannot justify adjacent unproved prose. '
                 'Keep genuine headers/footers separate from body content when needed. Repetition '
                 'alone cannot make a disclaimer or qualification disposable layout. '
                 'Every content part needs source-supported facts, with quotes entirely inside its '
                 'assigned range. If you classify a passage as content but cannot safely paraphrase '
                 'it, leave facts empty and explain that limitation. Its literal owned passage will '
                 'be retained as internal evidence requiring the independent slide editor. '
                 'Do not hide substance as headings/layout to pass validation.'}],
                SummaryReadBatch, blocks, cancelled, current)
            current['response'] = replacement.model_dump(mode='json')
            scoped = _owned_replacements(replacement, ranges, retained, lengths, current)
            replacement = replacement.model_copy(update={'parts': scoped})
            additions, errors = bind_reading(replacement, blocks, result, current,
                                            literal_fallback=True, recover_cross_part=True)
            combined = reconcile_layout(retained + additions, blocks, current)
            errors += reading_errors(probe(combined), result, complete_scope=False)
            current['errors'] = list(dict.fromkeys(errors))
            current['line_coverage'] = line_coverage(combined, blocks)
            # Root fields describe the current verdict. Earlier attempts and
            # their exact responses remain explicit historical audit records.
            record['errors'] = current['errors']
            record['line_coverage'] = current['line_coverage']
            if not errors:
                order = {b.id: i for i, b in enumerate(blocks)}
                return sorted(combined, key=lambda p: (order[p.block_id], p.start_line))
            feedback = _layout_feedback(additions, result)
            if (targeted_attempt or not set(errors) <= _LAYOUT_ERRORS or not feedback
                    or any(len(' '.join(p.source_text.split())) > 180 for p in additions
                           if p.id in {row['part_id'] for row in feedback})):
                raise ValueError('; '.join(current['errors']))
            # One further semantic decision is allowed only for still-invalid
            # short layout ranges. Python never promotes their meaning/content.
            failed_ids = {row['part_id'] for row in feedback}
            failed = [p for p in additions if p.id in failed_ids]
            retained = [p for p in combined if p.id not in failed_ids]
            ranges = _whole_part_ranges([dict(block_id=p.block_id, start_line=p.start_line,
                                             end_line=p.end_line) for p in failed], failed)
            current = {'ranges': ranges, 'rejected_parts': [dict(block_id=p.block_id,
                start_line=p.start_line, end_line=p.end_line, errors=current['errors'],
                previous_part=p.model_dump(mode='json')) for p in failed], 'layout_evidence': feedback,
                'previous_errors': list(current['errors'])}
            record['layout_retry'] = current
    except Exception as exc:
        record['error'] = str(exc)
        record['errors'] = list(current.get('errors', [])) or [str(exc)]
        if isinstance(exc, LLMStructuredOutputError):
            record['raw_response'] = exc.response.text
        if isinstance(exc, ValueError):
            raise ValueError('Summary targeted reading failed: ' + str(exc)) from exc
        raise


def _layout_feedback(parts, result):
    from adaptive_document_agent.services.summary_layout_evidence import layout_line_evidence
    feedback = []
    for part in parts:
        if part.role != 'layout':
            continue
        evidence = layout_line_evidence(part.source_text, part.source_page, result)
        if all(line['proved'] for line in evidence):
            continue
        feedback.append({'part_id': part.id, 'block_id': part.block_id, 'source_page': part.source_page,
            'lines': [{**line, 'line': part.start_line + line['line'] - 1} for line in evidence]})
    return feedback


def _owned_replacements(replacement, ranges, retained, lengths, record):
    scoped = []
    for candidate in replacement.parts:
        if any(candidate.block_id == r['block_id'] and
               r['start_line'] <= candidate.start_line <= candidate.end_line <= r['end_line'] for r in ranges):
            scoped.append(candidate)
            continue
        # A repeated accepted part is ignored; a boundary-crossing proposal or
        # an unknown source line still cannot overwrite accepted evidence.
        owned = {line for part in retained if part.block_id == candidate.block_id
                 for line in range(part.start_line, part.end_line + 1)}
        if (1 <= candidate.start_line <= candidate.end_line <= lengths.get(candidate.block_id, 0)
                and set(range(candidate.start_line, candidate.end_line + 1)) <= owned):
            record.setdefault('ignored_out_of_scope_parts', []).append(candidate.model_dump(mode='json'))
        else:
            raise ValueError('Summary targeted reading changed already accepted source lines')
    if not scoped:
        raise ValueError('Summary targeted reading returned no requested source ranges')
    return scoped


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
