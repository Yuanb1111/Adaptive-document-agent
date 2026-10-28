"""Bounded single-item fallback after a multi-item semantic review is truncated."""
from copy import deepcopy
import json

from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .presentation_budget_output import complete_budget_output
from .prompting import untrusted_document_message
from .topic_review_output import is_truncated


def complete_meaning_output(gateway, messages, schema, pending, record, capacity, *, cancelled=None):
    """Partition verdict work only; retain all shared context and exact item evidence."""
    limits = (16384, 24576)
    record['output_attempts'] = []
    if not capacity.get('single_item') or len(pending) == 1:
        try:
            return complete_budget_output(gateway, messages, schema, record,
                audit_key='output_attempts', token_limits=limits, stage='report', cancelled=cancelled)
        except LLMStructuredOutputError as exc:
            if not is_truncated(exc) or len(pending) <= 1:
                raise
            capacity['single_item'] = True
            record['partition_reason'] = 'Multi-item review exhausted bounded output capacity.'

    shared = next((row['available_report_context'] for row in pending
                   if 'available_report_context' in row), None)
    record['single_item_batches'] = []
    verdicts = []
    for row in pending:
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
        response = complete_budget_output(gateway, request, schema, batch,
            audit_key='output_attempts', token_limits=limits, stage='report', cancelled=cancelled)
        if len(response.items) != 1 or response.items[0].index != row['index']:
            raise ValueError('Brief meaning review must cover every exact supplied index in its capacity partition')
        verdicts.extend(response.items)
    # The caller still checks references, arithmetic, source meaning and
    # independent audience direction; concatenation cannot establish approval.
    return schema(items=verdicts)
