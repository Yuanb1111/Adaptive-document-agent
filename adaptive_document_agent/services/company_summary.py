"""Retrieve Summary context without issuer-specific headings or business templates."""

import re

from adaptive_document_agent.models import DocumentProfile, ParsedDocument


def summary_page_numbers(document: ParsedDocument) -> list[int]:
    """Find explicit Summary running headers, excluding contents entries.

    Heading-only evidence is a retrieval hint. The planner decides which
    subsection describes the issuer and which other topic is worth explaining.
    """
    selected = []
    for page in document.pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        headings = lines[:8] + lines[-4:]
        if any(re.fullmatch(r"(?i)(?:summary|executive\s+summary|概要|摘要)", line)
               for line in headings):
            if not re.search(r"(?im)^\s*(?:contents|table of contents|目錄|目录)\s*$", page.text):
                selected.append(page.page_number)
    return selected


def summary_excerpts(document: ParsedDocument, profile: DocumentProfile | None = None) -> list[dict]:
    """Offer diverse candidates; the LLM decides their semantic role.

    A familiar heading is a priority hint, not an eligibility requirement.
    Previously discovered context, ranked issuer pages and introductory pages
    cover differently named sections and pages without running headers.
    """
    from .company_discovery import CompanyProfileDiscovery

    anchors = list(dict.fromkeys([
        *(profile.document_summary_pages if profile else []),
        *CompanyProfileDiscovery.rank_profile_pages(document, profile, max_pages=10),
    ]))
    candidates = list(dict.fromkeys([
        *summary_page_numbers(document)[:20],
        *anchors,
        *(p + offset for p in anchors for offset in (-1, 1, 2)),
        *range(1, min(document.page_count, 40) + 1),
    ]))
    by_number = {p.page_number: p for p in document.pages if p.text.strip()}
    selected = [p for p in candidates if p in by_number][:60]
    return [{"page": p, "text": by_number[p].text[:6000],
             "text_truncated": len(by_number[p].text) > 6000,
             "retrieval_role": "candidate_only_model_must_classify"}
            for p in sorted(selected)]


def validate_summary(company, result) -> list[str]:
    """Check per-item quotation, page boundary and numeric support."""
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

    errors = []
    candidate_text = {p["page"]: p["text"] for p in summary_excerpts(result.document, result.profile)}
    normalize = lambda text: " ".join(text.casefold().split())
    for field in ("summary_overview", "summary_business"):
        page = getattr(company, field)
        if page is None:
            continue
        for item in page.items:
            if not set(item.source_pages) <= candidate_text.keys():
                errors.append(f"{field}: citations must belong to supplied company introduction candidates")
            quote = normalize(item.source_quote)
            if not any(quote in normalize(candidate_text.get(p, "")) for p in item.source_pages):
                errors.append(f"{field}: supporting quote is absent from cited pages")
            claimed = PresentationPlanValidator._numbers(item.label + " " + item.text)
            allowed = PresentationPlanValidator._numbers(item.source_quote)
            if claimed - allowed:
                errors.append(f"{field}: unsupported numeric claims {sorted(claimed - allowed)}")
    if bool(company.summary_overview) != bool(company.summary_business):
        errors.append("company Summary introduction requires both overview and business pages")
    return errors
