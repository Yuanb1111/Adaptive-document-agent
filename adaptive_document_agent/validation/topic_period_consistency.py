"""Bind a model's explicit shared comparison range to each selected source row.

A year elsewhere in a topic is not period evidence for a different series.
Recovery can change a period-specific series reference only when the retained
catalog has one exact same-source-row alternative. Raw observations never change.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from adaptive_document_agent.models import ValidationIssue
from .direction_scope import _PERIOD, _RANGE


def shared_question_range(topic):
    """Recognise one explicit range; independently labelled ranges stay separate."""
    matches = list(_RANGE.finditer(topic.question))
    if len(matches) != 1:
        return None
    match = matches[0]
    prefix, suffix = topic.question[:match.start()], topic.question[match.end():]
    # Recognition is deliberately bounded to a shared terminal comparison in
    # one question clause. A range followed by a separately reported panel, or
    # a range inside a subordinate/independent clause, must not reselect it.
    if re.search(r'[;?!]|\.(?:\s|$)|\b(?:alongside|separately|whereas|while|versus)\b', prefix, re.I):
        return None
    if suffix.strip() and not re.fullmatch(r'[?.!]+', suffix.strip()):
        # Source-scope reconciliation may append its separately retained
        # definition after the question. It must be a literal label: definition
        # caveat with no question or period, never a second analytical clause.
        tail = re.sub(r'^[?.!]\s*', '', suffix.strip(), count=1)
        if (tail not in topic.caveats or ':' not in tail or '?' in tail
                or re.search(rf'\b{_PERIOD}\b', tail, re.I)):
            return None
    # Another endpoint belongs to a different panel, not the shared range.
    remainder = topic.question[:match.start()] + topic.question[match.end():]
    if re.search(rf'\b{_PERIOD}\b', remainder, re.I):
        return None
    normalize = lambda s: re.sub(r'\s+', '', s).upper()
    start, end = normalize(match['start']), normalize(match['end'])
    if start == end:
        return None
    return start, end


def _period_matches(label, item, *, year_end=False):
    period = re.sub(r'\s+', '', item.period or '').upper()
    if period == label and re.fullmatch(r'(?:19|20)\d{2}', period):
        # A literal calendar-year label is not an assertion of fiscal-year
        # semantics. Explicitly contradictory interim typing is still invalid.
        return (item.period_basis.upper() in {'', 'GENERIC', 'FY', 'YEAR', 'ANNUAL'}
                and item.period_type in {'generic', 'fiscal_year', 'calendar_year', 'year'})
    from adaptive_document_agent.services.presentation_period_scope import _period
    valid_date = bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', period)
        and item.period_type in {'point_in_time', 'balance_sheet_date'})
    if _period(item) is None and not valid_date:
        return False
    if period == label:
        return True
    if re.fullmatch(r'(?:FY)?(?:19|20)\d{2}', label):
        year = label.removeprefix('FY')
        if period in {year, 'FY'+year}:
            return (period.startswith('FY') or item.period_basis == 'FY'
                    or item.period_type == 'fiscal_year')
        if year_end and item.period_type in {'point_in_time','balance_sheet_date'}:
            return period == year+'-12-31'
    return False


def _covers(group, scope, topic):
    context = ' '.join((topic.question, topic.title, topic.takeaway))
    year_end = bool(re.search(r'\byear[- ]end\b', context, re.I))
    return all(any(_period_matches(label, item, year_end=year_end) for item in group) for label in scope)


def topic_period_errors(topic, lookup):
    scope = shared_question_range(topic)
    if scope is None:
        return []
    return [f"Topic {topic.id} period range {scope[0]} to {scope[1]} is not supported by selected series {sid}."
            for sid in topic.series_ids if sid in lookup and not _covers(lookup[sid], scope, topic)]


def _source_row(group):
    from adaptive_document_agent.services.presentation_period_scope import _subject
    keys = {(_subject(item), item.row_id, item.raw_unit, item.unit_family, item.source_section) for item in group}
    if len(keys) != 1 or next(iter(keys))[0] is None:
        return None
    return next(iter(keys))


def _eligible(group):
    import math
    return bool(group) and all(item.value is not None and math.isfinite(item.value)
        and item.evidence and item.validation_status == 'valid' and not item.anomaly_notes for item in group)


def reconcile_topic_periods(result, lookup):
    """Resolve explicit temporal intent on a per-topic transaction, with audit.

    No fuzzy metric matching, different source table, missing period synthesis,
    omitted series, or ambiguous alternative is eligible. An unresolved topic is
    unchanged and remains subject to the ordinary validation/correction gates.
    """
    selection = result.presentation_topics
    if selection is None:
        return set()
    omitted = {item.series_id for item in selection.omissions}
    by_row = defaultdict(list)
    for sid, group in lookup.items():
        key = _source_row(group)
        if key is not None and _eligible(group):
            by_row[key].append(sid)
    changed = set()
    for topic in selection.topics:
        scope = shared_question_range(topic)
        if scope is None or any(sid not in lookup for sid in topic.series_ids):
            continue
        replacements = {}
        for sid in topic.series_ids:
            group = lookup[sid]
            if _covers(group, scope, topic):
                continue
            key = _source_row(group)
            candidates = [candidate for candidate in by_row.get(key, [])
                if candidate not in omitted and _covers(lookup[candidate], scope, topic)]
            if len(candidates) != 1:
                break
            replacements[sid] = candidates[0]
        else:
            if not replacements:
                continue
            updated = [replacements.get(sid, sid) for sid in topic.series_ids]
            if len(updated) != len(set(updated)):
                continue
            original = topic.model_dump(mode='json')
            topic.series_ids = updated
            audit = json.dumps({'original_topic': original, 'replacements': replacements,
                'period_range': list(scope), 'reason': 'Unique retained same-source-row series matches the explicit question periods.'},
                sort_keys=True, ensure_ascii=False)
            ids = list(dict.fromkeys(item.id for sid in {*replacements, *replacements.values()} for item in lookup[sid]))
            result.validation_warnings.append(ValidationIssue(code='presentation_topic_period_rebound',
                stage='presentation', severity='info', message=audit, related_ids=[topic.id, *ids],
                evidence=[e for sid in replacements.values() for item in lookup[sid] for e in item.evidence]))
            changed.add(topic.id)
    return changed


def continuation_copy(question, reason, observations):
    """A continuation cannot borrow periods or numbers from another page."""
    from .presentation_plan_validator import PresentationPlanValidator
    from adaptive_document_agent.document_model import period_sort_key
    from adaptive_document_agent.services.presentation_labels import qualified_metric_name
    allowed = set().union(*(PresentationPlanValidator._numbers(str(value)) for item in observations
        for value in (item.value,item.raw_value,item.period,item.entity,item.dimensions) if value is not None))
    def supported(text):
        year_end = bool(re.search(r'\byear[- ]end\b', text, re.I))
        periods_supported = all(any(_period_matches(re.sub(r'\s+', '', match.group()).upper(), item,
            year_end=year_end) for item in observations)
            for match in re.finditer(rf'\b{_PERIOD}\b', text, re.I))
        return periods_supported and not (PresentationPlanValidator._numbers(text) - allowed)

    if supported(question):
        return question, reason if supported(reason) else ''
    groups = defaultdict(set)
    for item in observations:
        if item.period:
            groups[qualified_metric_name(item)].add(item.period)
    detail = '; '.join(label+': '+', '.join(sorted(periods,key=period_sort_key)) for label,periods in groups.items())
    return 'How do the reported values compare?', 'Displayed evidence: '+detail if detail else ''
