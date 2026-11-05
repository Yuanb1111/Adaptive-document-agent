"""Literal source-page citations shared by review packets and slide rendering."""


def evidence_pages(insight, observations) -> list[int]:
    return sorted({e.page for o in observations for e in o.evidence}
                  | {e.page for e in insight.evidence})


def source_footer(pages: list[int] | set[int] | tuple[int, ...]) -> str:
    """Return the standardized client-facing source provenance footer."""
    normalized = sorted({int(page) for page in pages if int(page) > 0})
    if not normalized:
        return "Source: Document disclosures (page references not available)"
    ranges = []
    start = end = normalized[0]
    for page in normalized[1:]:
        if page == end + 1:
            end = page
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = page
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return f"Source: Document disclosures (p. {', '.join(ranges)})"
