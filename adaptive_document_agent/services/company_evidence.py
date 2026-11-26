"""Conservative issuer-bound source windows for deterministic profile recovery.

Page relevance is not entity attribution. Competitor tables and ownership
histories can be relevant to discovery without describing the document issuer.
"""

import re


_LEGAL_NAME = re.compile(
    r"^[A-Z][A-Z0-9&.,' ()-]{2,90}?\s+(?:CO\.?\s*,?\s*LTD\.?|"
    r"PTE\.?\s*LTD\.?|CORP\.?\s+LTD\.?|HOLDINGS\s+LIMITED|"
    r"LIMITED|CORPORATION|CORP\.?|INCORPORATED|INC\.?|LTD\.?)$", re.I)
_MIXED = re.compile(r"\bindustry\s+overview\b|\bcompetitors?\b|\bmarket\s+players\b|"
                    r"\b(?:history\s+and\s+)?corporate\s+structure\b|\bshareholders?\b", re.I)
_OTHER_ROW = re.compile(r"^(?:\d+\s+)?Company\s+(?:[A-Z]|\d+)\b")


def cover_name(sources: list[tuple[int, str]]) -> tuple[str, int] | None:
    """Accept complete legal-name lines only on the cover, never suffix fragments."""
    candidates = []
    for page, text in sources:
        if page != 1:
            continue
        for line in text.splitlines():
            line = line.strip()
            if _LEGAL_NAME.fullmatch(line) and not re.fullmatch(
                r"(?i)(?:group|company|holdings|corp\.?)(?:\s+co\.?,?)?\s+(?:ltd\.?|limited)", line
            ):
                candidates.append((line, page))
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else None


def recover_cover_identity(result):
    """Repair an older presentation that stored its generated overview title as the issuer."""
    plan = result.presentation_plan
    if not plan or result.finalization is not None or plan.company.summary_review is not None:
        return
    company = plan.company
    name = (company.name or '').strip()
    if not name or company.identity_state == 'UNRESOLVED' or name != result.profile.overview_title:
        return
    cited = set(company.field_source_pages.get('name') or company.source_pages)
    normalized_name = ' '.join(name.casefold().split())
    if any(normalized_name in ' '.join(p.text.casefold().split())
           for p in result.document.pages if p.page_number in cited):
        return

    front = {p.page_number: p.text for p in result.document.pages[:2]}
    # A title page may track individual letters apart or join the incorporation note
    # to the legal name. Accept a spelling only if it is also a complete legal-name
    # line on the next physical page. A partial match or competing name cannot win.
    def key(text):
        return ''.join(text.split()).casefold()

    cover_lines = [key(line) for line in front.get(1, '').splitlines() if line.strip()]
    title_lines = [line.strip() for line in front.get(2, '').splitlines() if line.strip()]
    names = set()
    for i, line in enumerate(title_lines):
        if not _LEGAL_NAME.fullmatch(line):
            continue
        registration = ' '.join(title_lines[i + 1:i + 3])
        if not re.search(r'\b(?:incorporated|registered|established)\s+(?:in|under)\b', registration, re.I):
            continue
        full = key(line)
        if any(cover == full or cover.startswith(full + '(') for cover in cover_lines):
            names.add(line)
    if len(names) != 1:
        return
    legal_name, = names
    from .company_extractor import validate_company_name
    if not validate_company_name(legal_name):
        return
    company.name = legal_name
    company.field_source_pages = {**company.field_source_pages, 'name': [1, 2]}
    company.source_pages = sorted(set(company.source_pages) | {1, 2})


def issuer_windows(sources: list[tuple[int, str]], name: str) -> list[tuple[int, str]]:
    """Keep issuer prose, excluding third-party rows and mixed-page fragments.

    On a mixed-entity page only an explicit issuer/our-company row is usable.
    Unlabelled continuations are deliberately omitted rather than guessed.
    """
    output = []
    for page, text in sources:
        mixed = bool(_MIXED.search(text) or any(_OTHER_ROW.match(line.strip()) for line in text.splitlines()))
        if not mixed:
            output.append((page, text))
            continue
        lines = text.splitlines()
        kept = []
        active = False
        remaining = 0
        for line in lines:
            stripped = line.strip()
            issuer = bool(re.search(r"(?i)\bour\s+company\b", stripped))
            issuer = issuer or bool(name and stripped.casefold().startswith(name.casefold()))
            if issuer:
                active = True
                remaining = 3
            elif _OTHER_ROW.match(stripped) or re.match(r"^\d+\s*$|^[•–—-]\s", stripped):
                active = False
            elif not stripped:
                active = False
            if active and remaining:
                kept.append(line)
                remaining -= 1
        if kept:
            output.append((page, "\n".join(kept)))
    return output


def supported_field(value: str, pages: list[int], sources: list[tuple[int, str]]) -> bool:
    """A cited literal must occur in an issuer-bound window, not just that page."""
    key = " ".join(value.casefold().split())
    return any(page in pages and key in " ".join(text.casefold().split()) for page, text in sources)
