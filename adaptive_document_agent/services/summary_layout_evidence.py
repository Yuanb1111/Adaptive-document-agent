"""Prove mechanical layout from literal source positions, never paragraph length."""
import re


def mechanical_layout(source: str, page_number: int, result) -> bool:
    text = ' '.join(source.split())
    if not text:
        return True
    page = next((p for p in result.document.pages if p.page_number == page_number), None)
    if page is None:
        return False
    lines = [line.strip() for line in page.text.splitlines() if line.strip()]
    if lines and text == lines[-1] and (
            re.fullmatch(r'[^\w]+(?:\d+|[ivxlcdm]+)[^\w]+', text, re.I)
            or re.fullmatch(r'page\s+\d+', text, re.I)):
        return True
    # A literal header containing only calendar/unit fields is structural.
    tokens = r'(?:as|at|of|for|the|year|years|ended|ending|six|three|months?|December|June|RMB|CNY|USD|HKD|in|thousands?|millions?|billions?|unaudited|audited)'
    remainder = re.sub(rf'(?i)\b{tokens}\b|[\d\s,;:()/%\-]+', '', text)
    if not remainder and re.search(r'(?i)\b(?:19|20)\d{2}\b', text):
        return True
    # Resolved table headers may contain dates, units and multi-tier labels.
    for table in page.tables + page.raw_tables:
        header = ' '.join(' '.join(table.raw_header_lines).split())
        if header and text in header:
            return True
    # Repeated edge text supplies running-header/footer evidence. A short
    # sentence in the body cannot qualify simply because it is short.
    def edge_lines(p):
        lines = [' '.join(line.split()) for line in p.text.splitlines() if line.strip()]
        return {lines[0], lines[-1]} if lines else set()
    return text in edge_lines(page) and sum(text in edge_lines(p) for p in result.document.pages) >= 2
