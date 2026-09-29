"""Bind each explicit share clause to its own source row and denominator."""

from dataclasses import dataclass
import re


SHARE_WORD = re.compile(r"\b(?:shares?|proportions?|percentage of (?:the )?total)\b", re.I)
_UP = re.compile(r"\b(?:increas\w*|rais\w*|rose|rising|grew|growing|higher|larger|expand\w*|gain\w*)\b", re.I)
_DOWN = re.compile(r"\b(?:decreas\w*|declin\w*|fell|falling|lower|smaller|shr\w*|contract\w*|lost|losing)\b", re.I)


def normalized(text):
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def source_row(item):
    labels = {e.row_label.strip() for e in item.evidence if e.row_label and e.row_label.strip()}
    return next(iter(labels)) if len(labels) == 1 else ""


def row_position(item, text):
    label = re.sub(r"(?i)^subtotal\s+of\s+|\s+markets?$", "", source_row(item))
    key, copy = normalized(label), normalized(text)
    match = re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", copy) if key else None
    return match.start() if match else -1


def reported_denominator(item):
    if item.unit not in {"percent", "percentage", "%"}:
        return ""
    denominators = set()
    for evidence in item.evidence:
        match = re.fullmatch(r"\s*(?:%|percentage|share)\s*of\s*(?:the\s*)?(.+?)\s*", evidence.column_label or "", re.I)
        if match:
            denominators.add(normalized(match.group(1)))
    return next(iter(denominators)) if len(denominators) == 1 else ""


def source_total_denominators(result):
    """Resolve 'Total' only when the exact table caption names its population."""
    from adaptive_document_agent.extraction.comparison_context import _caption_subject
    subjects = {}
    for page in result.document.pages:
        for table in page.tables:
            subject = _caption_subject(table) or ""
            # 'Revenue by geographic market' explicitly names the measure.
            # Generic financial sections and other tables cannot supply it.
            measure = re.split(r"\s+by\s+", subject, maxsplit=1, flags=re.I)[0]
            subjects.setdefault(table.table_id, set()).add(normalized(measure))
    return {key: next(iter(values)) for key, values in subjects.items()
            if len(values) == 1 and next(iter(values))}


def denominator_matches(item, wanted, totals):
    reported = reported_denominator(item)
    if reported == wanted:
        return True
    measure = totals.get(item.effective_table_id, "")
    return reported == "total" and bool(measure) and wanted in {measure, "total " + measure}


def share_motion(text):
    return bool(_UP.search(text)), bool(_DOWN.search(text))


@dataclass(frozen=True)
class ShareClaim:
    subject: str
    text: str
    denominator: str


def _row_mentions(selected, text):
    mentions = []
    rows = {source_row(item) for item in selected} - {""}
    labels = {row: re.findall(r"[^\W_]+", re.sub(r"(?i)^subtotal\s+of\s+|\s+markets?$", "", row))
              for row in rows}
    prefixes = {}
    for row, words in labels.items():
        if len(words) >= 3 and words[-2].casefold() not in {"of", "and", "the"}:
            prefixes.setdefault(tuple(word.casefold() for word in words[:-1]), set()).add(row)
    for row, words in labels.items():
        forms = [words]
        prefix = tuple(word.casefold() for word in words[:-1])
        if prefix in prefixes and prefixes[prefix] == {row}:
            forms.append(words[:-1])
        for form in forms:
            pattern = r"(?<!\w)" + r"[\W_]+".join(re.escape(word) for word in form) + r"(?!\w)"
            mentions.extend((m.start(), m.end(), row) for m in re.finditer(pattern, text, re.I))
    # A complete metric label wins over a substring such as Revenue inside
    # Deferred revenue. Identically positioned, distinct labels stay ambiguous.
    return [m for m in mentions if not any(n[0] <= m[0] and m[1] <= n[1]
            and n[1] - n[0] > m[1] - m[0] for n in mentions)]


def share_claims(selected, text):
    """Return independent clauses, or None for an ambiguous asserted subject.

    Conjunctions inside an explicit source row label are not clause boundaries.
    A directionless question makes no directional assertion. An ``its`` clause
    can use only an immediately preceding explicit, unambiguous source row.
    """
    if not SHARE_WORD.search(text):
        return []
    if re.match(r"\s*(?:how|what|which)\b", text, re.I) and not any(share_motion(text)):
        return []
    mentions = _row_mentions(selected, text)
    separators = [m for m in re.finditer(r"[,;!?]|(?<!\d)\.(?!\d)|\b(?:while|whereas|and|but)\b", text, re.I)
                  if not any(start <= m.start() and m.end() <= end for start, end, _ in mentions)]
    bounds = [0, *[position for m in separators for position in (m.start(), m.end())], len(text)]
    claims, previous, previous_bare, previous_compound = [], "", False, False
    for start, end in zip(bounds[::2], bounds[1::2]):
        clause = text[start:end]
        share = SHARE_WORD.search(clause)
        local = [(left - start, right - start, row) for left, right, row in mentions if start <= left and right <= end]
        if share is None:
            rows = {row for _, _, row in local}
            previous = next(iter(rows)) if len(rows) == 1 else ""
            previous_bare = bool(previous and len(local) == 1 and not clause[:local[0][0]].strip()
                                 and re.fullmatch(r"\s*(?:['’]s)?\s*", clause[local[0][1]:]))
            previous_compound = bool(previous and len(local) == 1 and not previous_bare
                                     and not any(share_motion(clause)))
            continue
        # A shared predicate after 'A and B' cannot be validated as B alone.
        # Separate 'A share expanded and B share contracted' clauses are safe.
        if previous_bare:
            return None
        before = [item for item in local if item[1] <= share.start()]
        if before:
            closest = max(right for _, right, _ in before)
            subjects = {row for _, right, row in before if right == closest}
            if len(subjects) != 1:
                return None
            subject = next(iter(subjects))
            subject_start = min(left for left, right, row in before if right == closest and row == subject)
            subject_end = closest
        elif previous and re.match(r"\s*(?:(?:increas\w*|rais\w*|expand\w*|reduc\w*)\s+)?its\b", clause, re.I):
            subject, subject_start, subject_end = previous, 0, 0
        elif (previous_compound and not local
              and re.fullmatch(r"\s*(?:[\w-]+\s+)?", clause[:share.start()])):
            # "Category sales volume and revenue share rose" keeps the one
            # explicit source row across the two measures. The denominator and
            # direction still have to pass their independent evidence checks.
            subject, subject_start, subject_end = previous, 0, 0
        else:
            return None
        denominator = ""
        tail = clause[share.end():]
        explicit = re.match(r"\s+of\s+(?:the\s+)?(.+)", tail, re.I)
        if explicit:
            value = re.split(r"\b(?:from|over|during|increas\w*|decreas\w*|declin\w*|rose|fell|grew|expand\w*|contract\w*|was|were|is|has|had)\b",
                             explicit.group(1), maxsplit=1, flags=re.I)[0]
            denominator = normalized(value)
            if not denominator:
                return None
        elif re.match(r"percentage of (?:the )?total", share.group(), re.I):
            denominator = "total"
        else:
            # A noun modifier is also an explicit denominator: 'revenue share'
            # must not quietly use a reported percentage of units instead.
            prefix = re.sub(r"^\s*['’]s\s*", "", clause[subject_end:share.start()]).strip()
            prefix = re.split(r"\b(?:its|their)\s+", prefix, flags=re.I)[-1]
            if prefix and not any(share_motion(prefix)) and re.fullmatch(r"[\w-]+(?:\s+[\w-]+){0,3}", prefix):
                denominator = normalized(prefix)
        claims.append(ShareClaim(subject, clause[subject_start:].strip(), denominator))
        previous, previous_bare, previous_compound = subject, False, False
    return claims


def share_direction_supported(shares, text, qualifications=()):
    up, down = share_motion(text)
    values = [float(item.value) for item in shares]
    magnitude = bool(re.search(r"\b(?:magnitude|absolute)\b", text, re.I)) or any(
        row_position(shares[0], note) >= 0 and re.search(r"\b(?:magnitude|absolute)\b", note, re.I)
        for note in qualifications)
    if magnitude:
        values = [abs(value) for value in values]
    change = values[-1] - values[0]
    return not ((up and change <= 0) or (down and change >= 0))
