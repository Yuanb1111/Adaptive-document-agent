"""Bounded single-item fallback after a multi-item semantic review is truncated."""
from copy import deepcopy
import json

from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .presentation_budget_output import complete_budget_output
from .prompting import untrusted_document_message
from .topic_review_output import is_truncated
from .brief_review_checkpoint import BriefReviewUnavailable
from .brief_review_progress import report_brief_progress

GROUP_LIMITS = (16384, 24576)
ITEM_LIMITS = (16384, 32768)


def _request(gateway, messages, schema, record, limits, label, cancelled):
    """One capacity retry; one format correction only for complete invalid output."""
    current = messages
    for format_attempt in range(2):
        physical = record if not format_attempt else record.setdefault('format_correction', {})
        def before_attempt():
            attempt = len(physical.get('output_attempts', []))
            report_brief_progress(f'{label}; ' + ('capacity retry' if attempt else 'request')
                                  + f' {attempt + 1}/2, output limit {limits[attempt]}')
        try:
            return complete_budget_output(gateway, current, schema, physical,
                audit_key='output_attempts', token_limits=limits, stage='report',
                cancelled=cancelled, before_attempt=before_attempt)
        except LLMStructuredOutputError as exc:
            if is_truncated(exc) or format_attempt:
                raise
            report_brief_progress(f'{label}; correcting complete response format once')
            current = messages + [{'role': 'user', 'content':
                'The complete response failed format validation. Return every exact requested index '
                'in the original schema. Keep all source, meaning and arithmetic checks. '
                'Use evidence references, not copied tables. Do not approve uncertain claims.'}]


def complete_meaning_output(gateway, messages, schema, pending, record, capacity, *,
                            cancelled=None, on_complete=None):
    """Partition verdict work only; retain all shared context and exact item evidence."""
    record['output_attempts'] = []
    if not capacity.get('single_item') and len(pending) > 1:
        try:
            response = _request(gateway, messages, schema, record, GROUP_LIMITS,
                                f'group of {len(pending)} items', cancelled)
        except LLMStructuredOutputError as exc:
            if not is_truncated(exc):
                raise BriefReviewUnavailable({row['index']: 'invalid_response_format'
                                              for row in pending}) from exc
            capacity['single_item'] = True
            record['partition_reason'] = 'Multi-item review exhausted bounded output capacity.'
        else:
            if on_complete is not None:
                on_complete(response, pending, messages)
            return response

    shared = next((row['available_report_context'] for row in pending
                   if 'available_report_context' in row), None)
    record['single_item_batches'] = []
    verdicts, failures = [], {}
    for position, row in enumerate(pending, 1):
        scoped = deepcopy(row)
        if shared is not None:
            scoped['available_report_context'] = deepcopy(shared)
        request = [dict(messages[0], content=messages[0]['content'] +
            ' This is a single-item capacity partition. Return only its exact supplied index. '
            'Review the whole current brief and all shared context for qualifications and '
            'companion findings, but produce a verdict only for this assigned item. '
            'Partitioning grants no approval and does not remove any meaning check.'),
            untrusted_document_message(json.dumps([scoped], ensure_ascii=False)),
            *messages[2:]]
        batch = dict(indices=[row['index']])
        record['single_item_batches'].append(batch)
        label = f'item {row["index"] + 1} ({position}/{len(pending)} pending)'
        try:
            response = _request(gateway, request, schema, batch, ITEM_LIMITS, label, cancelled)
        except LLMStructuredOutputError as exc:
            kind = 'output_capacity_exhausted' if is_truncated(exc) else 'invalid_response_format'
            batch['failure_kind'] = kind
            failures[row['index']] = kind
            report_brief_progress(f'{label}; unavailable ({kind}), checking remaining items')
            continue
        if len(response.items) != 1 or response.items[0].index != row['index']:
            raise ValueError('Brief meaning review must cover every exact supplied index in its capacity partition')
        batch['response'] = response.model_dump(mode='json')
        if on_complete is not None:
            on_complete(response, [scoped], request)
        verdicts.extend(response.items)
    # The caller still checks references, arithmetic, source meaning and
    # independent audience direction; concatenation cannot establish approval.
    record['unavailable'] = failures
    if failures:
        raise BriefReviewUnavailable(failures)
    return schema(items=verdicts)
