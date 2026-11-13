"""Owned-page copy corrections share the gateway limit and existing retry bounds."""
from concurrent.futures import ThreadPoolExecutor


def revise_owned_pages(issues, revise):
    """Return a complete unapproved replacement set, or drain and reject the batch."""
    from .retained_page_sources import AuthoredPageErrors
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
                failures.update(exc.by_insight)
            except Exception as exc:
                if fatal is None:
                    fatal = exc
    if fatal is not None:
        raise fatal
    if failures:
        raise AuthoredPageErrors(failures)
    return replacements
