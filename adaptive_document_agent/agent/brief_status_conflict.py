"""Conflicting source status can receive feedback, never automatic approval."""
import re
from .brief_audit_scope import _PERIOD, _period_keys


def retryable_status_conflict(error, inventory):
    match = re.match(r"Audit status '(audited|unaudited)' for '([^']+)' lacks", error)
    if not match:
        return False
    period = _PERIOD.fullmatch(match[2])
    if period is None:
        return False
    columns = [column for table in inventory for column in table['columns']]
    keys = _period_keys(period, columns)
    statuses = {column['status'] for column in columns
                if re.sub(r'\s+', '', column['period']).upper() in keys}
    # The assertion still fails. A same-period annotation exists, but is not
    # uniformly owned by these measures. Spend only the existing protocol retry
    # to remove/re-scope it; completely unsupported assurance is not retryable.
    return match[1] in statuses and len(statuses) > 1
