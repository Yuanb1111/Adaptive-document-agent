"""Compare atomic failed checks without treating a shorter message as progress."""
import re


def source_failure_keys(errors):
    failures = set()
    # Audit errors may contain several joined checks. Keep each item's identity
    # and accounting-sign failures instead of folding them into the first list.
    for error in (check for error in errors for check in error.split('.; ')):
        error = error.rstrip('.')
        prefix, separator, tail = error.partition('unsupported numeric claims ')
        tokens = re.findall(r"'([-+\d.,%]+)'", tail) if separator else []
        if tokens:
            failures.update(prefix + 'unsupported numeric claim ' + token for token in tokens)
        else:
            failures.add(error)
    return failures


def nonprogress_source_errors(candidate, *, catalog, review, result, errors, source=None):
    """Check complete repaired claims without consuming the layout/review budgets."""
    from .compact_summary import expand_compact
    from adaptive_document_agent.services.compact_summary import (
        compact_item_errors, compact_continuation_errors)
    candidate_review = review.model_copy(deep=True)
    pages = expand_compact(candidate, catalog, candidate_review)
    remaining, continuations = [], {}
    for page in pages:
        for item in page.items:
            if item.continuation_group:
                continuations.setdefault(item.continuation_group, []).append(item)
            else:
                remaining.extend(compact_item_errors(item, candidate_review, result))
    remaining.extend(compact_continuation_errors(continuations, candidate_review, result))
    if source is not None:
        from .summary_authored_coverage import authored_coverage_errors
        remaining.extend(authored_coverage_errors(candidate, source, catalog, {}))
    return remaining if (remaining and not source_failure_keys(remaining) < source_failure_keys(errors)) else []
