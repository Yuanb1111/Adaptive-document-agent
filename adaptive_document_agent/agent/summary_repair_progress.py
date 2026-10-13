"""Compare atomic failed checks without treating a shorter message as progress."""
import re


def source_failure_keys(errors):
    failures = set()
    for error in errors:
        prefix, separator, tail = error.partition('unsupported numeric claims ')
        tokens = re.findall(r"'([-+\d.,%]+)'", tail) if separator else []
        if tokens:
            failures.update(prefix + 'unsupported numeric claim ' + token for token in tokens)
        else:
            failures.add(error)
    return failures
