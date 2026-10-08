"""Merge identical displayed period rows while retaining every source record."""

import re
from copy import deepcopy

from adaptive_document_agent.document_model.series import is_generic_metric_label


def deduplicate_complete_entries(themes):
    """Merge exact partial corroboration, keeping conflicts and all provenance."""
    output = deepcopy(themes)
    plain = lambda text: re.sub(r" \[source \d+\]$", "", text)
    for entries in output.values():
        for key, entry in list(entries.items()):
            if key not in entries or len(key) < 7 or is_generic_metric_label(str(key[0])):
                continue
            for other_key, other in list(entries.items()):
                if key == other_key or other_key not in entries:
                    continue
                if (key[0], key[2:], entry['unit'], plain(entry['label'])) != (
                        other_key[0], other_key[2:], other['unit'], plain(other['label'])):
                    continue
                periods = set(other['values'])
                if len(periods) < 2 or not periods <= set(entry['values']):
                    continue
                if not all(other['values'][p] == entry['values'][p]
                           and other['raw_signatures'][p] == entry['raw_signatures'][p] for p in periods):
                    continue
                entry['pages'].update(other['pages'])
                entry['records'].extend(other['records'])
                del entries[other_key]
        names = [plain(entry['label']) for entry in entries.values()]
        for entry in entries.values():
            if names.count(plain(entry['label'])) == 1:
                entry['label'] = plain(entry['label'])
    return output


def deduplicate_period_entries(themes, periods):
    """Compare only this table's exact periods, raw values, units and scope.

    A source can have additional interim records without duplicating its annual
    values in an annual table. Conflicts, unknown labels and distinct bases stay
    separate. Copies prevent one period table from modifying another's evidence.
    """
    result = {}
    for theme, entries in themes.items():
        output, seen = {}, {}
        for identity, original in entries.items():
            entry = {**original, "pages": set(original["pages"]), "records": list(original["records"])}
            values = tuple((p, entry["values"][p]) for p in periods if p in entry["values"])
            raw = frozenset((p, frozenset(entry["raw_signatures"][p])) for p in periods
                            if p in entry["raw_signatures"])
            signature = (identity[0], identity[2:], entry["unit"], values, raw)
            eligible = len(identity) >= 7 and len(values) == len(periods) and len(values) >= 2
            eligible = eligible and not is_generic_metric_label(str(identity[0]))
            retained = seen.get(signature) if eligible else None
            if retained is None:
                output[identity] = entry
                if eligible:
                    seen[signature] = identity
            else:
                output[retained]["pages"].update(entry["pages"])
                output[retained]["records"].extend(entry["records"])
        plain = lambda label: re.sub(r" \[source \d+\]$", "", label)
        names = [plain(entry["label"]) for entry in output.values()]
        for entry in output.values():
            if names.count(plain(entry["label"])) == 1:
                entry["label"] = plain(entry["label"])
        result[theme] = output
    return result
