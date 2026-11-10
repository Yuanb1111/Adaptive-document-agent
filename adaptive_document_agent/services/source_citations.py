"""Literal source-page citations shared by review packets and slide rendering."""


def evidence_pages(insight, observations, *, document=None) -> list[int]:
    pages = ({e.page for o in observations for e in o.evidence}
             | {e.page for e in insight.evidence})
    if document is not None:
        # A driver quote can start on a continuation page. Preserve neighboring
        # pages so the model can read its paragraph's owner and scope. Proximity
        # alone never determines a year or establishes a causal relationship.
        prose_pages = {e.page for e in insight.evidence
                       if e.extraction_method == 'source_text_context'}
        if insight.driver_source_page is not None:
            prose_pages.add(insight.driver_source_page)
            pages.add(insight.driver_source_page)
        available = {p.page_number for p in document.pages}
        pages.update(n for p in prose_pages for n in (p - 1, p, p + 1) if n in available)
    return sorted(pages)


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
