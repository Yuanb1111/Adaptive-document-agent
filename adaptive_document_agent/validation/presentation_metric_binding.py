"""Lexical bindings derived from source labels, including shared subjects."""

from __future__ import annotations

import re


def ratio_label_forms(label: str) -> set[str]:
    """Derive ratio aliases from the source subject, without aliasing its inputs.

    A source label such as ``Annual support and maintenance expenditure ratio
    %`` also names ``S&M ratio``. Only a multi-word source prefix may elide a
    trailing noun; shared shortened aliases must still resolve uniquely.
    """
    forms: set[str] = set()
    clean = re.sub(r"\s*%\s*$", "", label).strip()
    for form in source_label_forms(clean):
        match = re.fullmatch(r"(.+?)\s+(ratio|share|percentage)(\b.*)", form, re.I)
        if not match:
            continue
        forms.add(form)
        words = match[1].split()
        for end in range(1, len(words)):
            prefix = " ".join(words[:end])
            tokens = [word for word in re.findall(r"[a-z0-9]+", prefix.casefold())
                      if word not in {"and", "the", "annual"}]
            if len(tokens) >= 2 and words[end - 1].casefold() not in {"and", "&", "of", "to"}:
                forms.add(f"{prefix} {match[2]}{match[3]}")
    return forms


def bind_compound_ratio_spans(
    clause: str,
    metric_spans: list[tuple[int, int, str]],
    direction_spans: list[tuple[int, int, str]],
    ambiguous_metric: str,
) -> list[tuple[int, int, str]]:
    """Keep ratio operands inside one subject before choosing its predicate.

    This binds lexical subjects only; it neither calculates a missing ratio nor
    establishes its denominator definition. An unknown ratio cannot borrow the
    trend of a known numerator or denominator, even if their values appear.
    """
    # "Percentage points" is a delta unit, not a second ratio subject.
    markers = re.compile(
        r"\b(?:ratio|share|percentage(?![\s-]+points?\b)|rate|margin)\b|%\s+of\b|\s/\s", re.I,
    )
    connector = re.compile(
        r"\s+(?:(?:as\s+)?(?:a\s+)?(?:percentage|percent|%|share)\s+of|"
        r"relative\s+to|to|of)\s+", re.I,
    )
    result = list(metric_spans)
    handled_until = -1
    for marker in markers.finditer(clause):
        if marker.start() < handled_until:
            continue
        covering = [(start, end, owner) for start, end, owner in result
                    if start <= marker.start() and end >= marker.end()]
        start = min((item[0] for item in covering), default=marker.start())
        end = max((item[1] for item in covering), default=marker.end())
        owners = {item[2] for item in covering} or {ambiguous_metric}
        relation = connector.match(clause, end)
        implicit_relation = marker.group().strip().startswith(('%', '/'))
        if relation or implicit_relation:
            # The predicate terminates the compound subject. Independent
            # predicates have already been split by the caller.
            end = next((ds for ds, _, _ in direction_spans if ds >= end), len(clause))
        if not covering:
            # Include the numerator too, so nearest-alias and single-metric
            # fallbacks cannot attach the predicate to a component instead.
            start = max((de for _, de, _ in direction_spans if de <= start), default=0)
        result = [(ms, me, owner) for ms, me, owner in result
                  if me <= start or ms >= end]
        result.extend((start, end, owner) for owner in sorted(owners))
        handled_until = end
    return sorted(result, key=lambda item: item[0])


def source_label_forms(label: str) -> set[str]:
    """Allow source-derived initialisms and an omitted annual qualifier."""
    forms = {label.strip()}
    for pair in re.finditer(r"\b([A-Za-z]+)\s+(?:and|&)\s+([A-Za-z]+)\b", label):
        forms.add(label[:pair.start()] + pair[1][0] + "&" + pair[2][0] + label[pair.end():])
    return forms | {re.sub(r"^annual\s+", "", form, flags=re.I) for form in forms}


def possessive_ratio_subject(clause: str, previous_clause: str, labels: dict[str, str]) -> str | None:
    """Bind a ratio pronoun to one source row naming the preceding subject."""
    if not re.match(r"\s*its\s+(?:ratio|share)\b", clause, re.I) or not previous_clause:
        return None
    candidates = []
    for key, label in labels.items():
        match = re.match(r"(.+?)\s+ratio\b", label, re.I)
        if match and any(re.search(r"\b" + re.escape(form) + r"\b", previous_clause, re.I)
                         for form in source_label_forms(match[1].strip())):
            candidates.append(key)
    return candidates[0] if len(candidates) == 1 else None


def coordinated_alias_owners(prefix: str, owners: set[str]) -> list[str] | None:
    """Resolve every conjunct against source category prefixes before a colon.

    Shared trailing category words can be elided ("Alpha and Beta devices").
    Every conjunct must identify one distinct source owner; partial matches
    and unknown categories remain unresolved.
    """
    def words(text: str) -> list[str]:
        return [word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
                for word in re.findall(r"[a-z0-9]+", text.casefold())]

    categories = {owner: words(owner.split(":", 1)[0]) for owner in owners if ":" in owner}
    if len(categories) != len(owners) or len(owners) < 2:
        return None
    shared = 0
    while all(len(tokens) > shared + 1 for tokens in categories.values()):
        if len({tokens[-shared - 1] for tokens in categories.values()}) != 1:
            break
        shared += 1
    parts = re.split(r"\s*(?:,\s*(?:and\s+)?|\band\b|&)\s*", prefix.strip(), flags=re.I)
    if len(parts) < 2:
        return None
    result = []
    for part in parts:
        tokens = words(part)
        matches = [owner for owner, category in categories.items()
                   if tokens == category or (shared and tokens == category[:-shared])]
        if len(matches) != 1 or matches[0] in result:
            return []
        result.append(matches[0])
    return result
