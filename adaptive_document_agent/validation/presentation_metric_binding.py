"""Lexical bindings derived from source labels, including shared subjects."""

from __future__ import annotations

import re


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
