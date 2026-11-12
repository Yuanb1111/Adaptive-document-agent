"""Request independent literal verdicts concurrently; validate only on caller."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from copy import deepcopy
import json
from queue import Empty, SimpleQueue
from threading import Event

from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .topic_review_output import is_truncated

from .brief_meaning_capacity import _request, ITEM_LIMITS
from .brief_review_checkpoint import BriefReviewUnavailable
from .brief_review_progress import brief_progress, report_brief_progress
from .prompting import untrusted_document_message


def literal_partitions(gateway, messages, schema, pending, record, *, cancelled=None):
    """Only after whole-context work has its own mandatory independent gate.

    Every request keeps its complete owned evidence. Workers return unapproved
    verdicts; the caller still checks evidence, arithmetic, audience direction,
    whole-brief context and checkpoints. No worker mutates pipeline results.
    """
    stopped = cancelled if cancelled is not None else Event()
    events = SimpleQueue()
    records = record['parallel_literal_partitions'] = [dict(index=row['index']) for row in pending]

    def request(position, row):
        scoped = deepcopy(row)
        request_messages = [dict(messages[0], content=messages[0]['content'] +
            ' This is one independent literal-item partition. Return ONLY its exact supplied index. '
            'Keep every owned quotation, source, arithmetic and meaning check. A separate mandatory '
            'review checks all shared source blocks and the whole brief; partitioning grants no approval.'),
            untrusted_document_message(json.dumps([scoped], ensure_ascii=False)), *messages[2:]]
        audit = records[position]
        with brief_progress(events.put):
            try:
                response = _request(gateway, request_messages, schema, audit, ITEM_LIMITS,
                                    f'item {row["index"] + 1} literal review', stopped)
            except LLMStructuredOutputError as exc:
                kind = 'output_capacity_exhausted' if is_truncated(exc) else 'invalid_response_format'
                audit['failure_kind'] = kind
                raise BriefReviewUnavailable({row['index']:kind}) from exc
        if len(response.items) != 1 or response.items[0].index != row['index']:
            raise ValueError('Literal partition must review its one exact assigned index')
        audit['response'] = response.model_dump(mode='json')
        return response, [scoped], request_messages

    def drain():
        while True:
            try:report_brief_progress(events.get_nowait().removeprefix('Briefing review: '))
            except Empty:return

    pool = ThreadPoolExecutor(max_workers=min(4,len(pending)),thread_name_prefix='brief-literal-review')
    futures = {pool.submit(copy_context().run,request,i,row):row['index'] for i,row in enumerate(pending)}
    waiting = set(futures)
    failures = {}
    try:
        while waiting:
            done,waiting = wait(waiting,timeout=.25,return_when=FIRST_COMPLETED)
            drain()
            for future in done:
                try:
                    yield future.result()
                except BriefReviewUnavailable as exc:
                    failures.update(exc.failures)
                except Exception:
                    stopped.set()
                    raise
        if failures:
            raise BriefReviewUnavailable(failures)
    finally:
        for future in futures:future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)
        drain()
