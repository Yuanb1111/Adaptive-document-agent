"""Owned-page copy corrections share the gateway limit and existing retry bounds."""
from concurrent.futures import ThreadPoolExecutor

from .retained_page_sources import AuthoredPageErrors


class OwnedPageRevisionErrors(AuthoredPageErrors):
    """A drained batch failed; successful siblings are still unapproved drafts."""

    def __init__(self, failures, unapproved_pages):
        super().__init__(failures)
        self.unapproved_pages = unapproved_pages


def revise_owned_pages(issues, revise):
    """Return a complete unapproved replacement set, or drain and reject the batch."""
    replacements, failures, fatal = {}, {}, None
    with ThreadPoolExecutor(max_workers=min(4, len(issues))) as pool:
        pending = {iid: pool.submit(revise, {iid: reasons}) for iid, reasons in issues.items()}
        for iid, future in pending.items():
            try:
                owned = future.result()
                if set(owned) != {iid}:
                    raise ValueError('Owned-page revision returned a different page set')
                replacements.update(owned)
            except AuthoredPageErrors as exc:
                if set(exc.by_insight) != {iid}:
                    fatal = fatal or ValueError('Owned-page revision reported a different page set')
                else:
                    failures.update(exc.by_insight)
            except Exception as exc:
                if fatal is None:
                    fatal = exc
    if fatal is not None:
        raise fatal
    if failures:
        raise OwnedPageRevisionErrors(failures, replacements)
    return replacements


def complete_owned_copy_revisions(issues, remaining, revise):
    """Spend the existing revision rounds on unresolved pages before rechecking the batch."""
    pending = issues
    drafts = {}
    while remaining:
        remaining -= 1
        try:
            completed = revise(pending)
        except AuthoredPageErrors as exc:
            siblings = exc.unapproved_pages if isinstance(exc, OwnedPageRevisionErrors) else {}
            failures = exc.by_insight
            if (not remaining or failures.keys() & siblings.keys()
                    or (failures.keys() | siblings.keys()) != pending.keys()):
                raise
            drafts.update(siblings)
            pending = {iid: list(dict.fromkeys([*pending[iid], *failures[iid]]))
                       for iid in pending if iid in failures}
        else:
            if completed.keys() != pending.keys():
                raise ValueError('Page revision did not cover the complete pending page set')
            drafts.update(completed)
            return drafts, remaining
    raise ValueError('No retained copy revision rounds remain')
