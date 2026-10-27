"""Retrieve nearby source context without deciding its analytical importance."""
import re


def companion_excerpts(result, selected, *, max_chars=24000, max_pages=6):
    """Keep literal nearby tables/narrative sharing selected source identities.

    A neighboring reconciliation, definition or alternative scenario is a
    reading candidate, not an automatically required metric or supported cause.
    Full source pages are preferred; bounded prefixes remain explicitly scoped
    by the briefing writer. No company/industry/metric vocabulary is imposed.
    """
    labels = {re.sub(r'\s+', ' ', o.metric_original).casefold().strip()
              for o in result.observations if any(e.page in selected for e in o.evidence)}
    labels = {label for label in labels if len(label) >= 3}
    if not labels:
        return {}
    neighbors = {p + step for p in selected for step in (-1, 1)} - selected.keys()
    candidates = []
    for page in result.document.pages:
        if page.page_number not in neighbors or not page.text.strip():
            continue
        normalized = re.sub(r'\s+', ' ', page.text).casefold()
        score = sum(label in normalized for label in labels)
        if score:
            candidates.append((score, page))
    output = {}
    for _, page in sorted(candidates, key=lambda item: (-item[0], item[1].page_number)):
        if len(output) >= max_pages or max_chars < 1200:
            break
        text = page.text[:min(9000, max_chars)]
        output[page.page_number] = text
        max_chars -= len(text)
    return output
