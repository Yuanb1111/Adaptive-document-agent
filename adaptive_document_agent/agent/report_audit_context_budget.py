"""Bound actual audit request contexts, not the local aggregate evidence ledger."""
import json

MAX_AUDIT_CONTEXT_CHARS = 150_000


def serialize_audit_context(context):
    """Remove only JSON separator whitespace, preserving every source character."""
    return json.dumps(context, ensure_ascii=False, separators=(',', ':'))


def audit_context_budget(context):
    """Measure the exact existing target partitions with every source page intact."""
    from .report_audit_batches import batch_context, batch_targets
    sizes = [len(serialize_audit_context(batch_context(context, ids)))
             for ids in batch_targets(context)]
    return dict(limit=MAX_AUDIT_CONTEXT_CHARS,
                aggregate_characters=len(serialize_audit_context(context)),
                target_count=len(context['observations']),
                source_page_count=len(context['source_pages']),
                batch_count=len(sizes), largest_batch_characters=max(sizes, default=0))


def require_audit_context_budget(context):
    """Never truncate sources, skip targets or increase the per-request allowance."""
    budget = audit_context_budget(context)
    if budget['largest_batch_characters'] > MAX_AUDIT_CONTEXT_CHARS:
        raise ValueError('Complete audit source pages exceed the 150000-character evidence budget '
                         f"in an actual review batch ({budget['largest_batch_characters']} characters); "
                         'no page was truncated and no target was omitted.')
    return budget
