"""Retrieve Summary context without issuer-specific headings or business templates."""

import re
from .source_quotes import normalize_quote

from adaptive_document_agent.models import DocumentProfile, ParsedDocument


def is_summary_heading(title: str) -> bool:
    """Recognize compound Summary headings as retrieval hints, not workflows."""
    return bool(re.fullmatch(
        r"(?i)(?:summary|executive\s+summary|概要|摘要)"
        r"(?:\s*(?:and|&|/|[–—:：-])\s*\S.*)?", title.strip()))


def summary_outline_pages(document: ParsedDocument) -> list[int]:
    return sorted({number for section in document.outline if is_summary_heading(section.title)
                   for number in range(section.start_page, section.end_page + 1)})


def summary_page_numbers(document: ParsedDocument) -> list[int]:
    """Find explicit Summary running headers, excluding contents entries.

    Heading-only evidence is a retrieval hint. The planner decides which
    subsection describes the issuer and which other topic is worth explaining.
    """
    selected = []
    for page in document.pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        headings = lines[:8] + lines[-4:]
        if any(is_summary_heading(line) for line in headings):
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
    explicit = set(summary_page_numbers(document)) | set(summary_outline_pages(document))
    candidates = list(dict.fromkeys([
        *sorted(explicit),
        *range(1, min(document.page_count, 40) + 1),
        *anchors,
        *(p + offset for p in anchors for offset in (-1, 1, 2)),
    ]))
    by_number = {p.page_number: p for p in document.pages if p.text.strip()}
    other = [p for p in candidates if p in by_number and p not in explicit][:60]
    selected = list(dict.fromkeys([*(p for p in candidates if p in explicit and p in by_number), *other]))
    return [{"page": p, "text": by_number[p].text[:6000],
             "text_truncated": len(by_number[p].text) > 6000,
             "retrieval_role": "candidate_only_model_must_classify"}
            for p in sorted(selected)]


def validate_summary(company, result) -> list[str]:
    """Check per-item quotation, page boundary and numeric support."""
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

    errors = []
    if company.summary_review is not None:
        from .summary_validation import presentation_errors
        errors.extend(presentation_errors(company.summary_review, company.summary_pages, result))
        if company.summary_review.status != 'complete':
            errors.append('Introductory Summary reading/selection is incomplete')
        if company.summary_overview or company.summary_business or company.value_chain:
            errors.append('Complete Summary introduction cannot mix legacy introductory pages')
        return errors
    elif company.summary_pages:
        errors.append('Dynamic Summary slides require their complete reading/decision audit')
    candidate_text = {p["page"]: p["text"] for p in summary_excerpts(result.document, result.profile)}
    normalize = normalize_quote
    for field in ("summary_overview", "summary_business"):
        page = getattr(company, field)
        if page is None:
            continue
        title_numbers = PresentationPlanValidator._numbers(page.title)
        quoted_numbers = set().union(*(PresentationPlanValidator._numbers(item.source_quote)
                                      for item in page.items))
        if title_numbers - quoted_numbers:
            errors.append(f"{field}: page title contains unsupported numeric claims {sorted(title_numbers - quoted_numbers)}")
        for item in page.items:
            if not set(item.source_pages) <= candidate_text.keys():
                errors.append(f"{field}: citations must belong to supplied company introduction candidates")
            quote = normalize(item.source_quote)
            if not quote or not any(quote in normalize(candidate_text.get(p, "")) for p in item.source_pages):
                errors.append(f"{field}: supporting quote is absent from cited pages")
            claimed = PresentationPlanValidator._numbers(item.label + " " + item.text)
            allowed = PresentationPlanValidator._numbers(item.source_quote)
            if claimed - allowed:
                errors.append(f"{field}: unsupported numeric claims {sorted(claimed - allowed)}")
    if company.value_chain and not 3 <= len(company.value_chain) <= 5:
        errors.append("value_chain: a sourced flow requires three to five distinct stages")
    for item in company.value_chain:
        if not set(item.source_pages) <= candidate_text.keys():
            errors.append("value_chain: citations must belong to supplied company introduction candidates")
        quote = normalize(item.source_quote)
        if not quote or not any(quote in normalize(candidate_text.get(p, "")) for p in item.source_pages):
            errors.append("value_chain: supporting quote is absent from cited pages")
        claimed = PresentationPlanValidator._numbers(item.label + " " + item.text)
        allowed = PresentationPlanValidator._numbers(item.source_quote)
        if claimed - allowed:
            errors.append(f"value_chain: unsupported numeric claims {sorted(claimed - allowed)}")
    return errors


def require_verified_introduction(result) -> None:
    """An explicitly failed introductory stage cannot become a delivered deck."""
    company = result.presentation_plan.company if result.presentation_plan else None
    attempted = any(issue.code in {'company_introduction_unavailable', 'company_introduction_selection_audit'}
                    for issue in result.validation_warnings)
    if attempted and (company is None or not (company.summary_overview or company.summary_business
                                               or company.summary_pages)):
        failure = next((issue.message for issue in reversed(result.validation_warnings)
                        if issue.code == 'company_introduction_unavailable'), '')
        raise ValueError('PowerPoint requires a source-verified opening introduction; '
                         'the introductory stage failed. Retry analysis (reuse successful cache) '
                         'to resume the incomplete reporting stage.'
                         + (' Reason: ' + failure if failure else ''))
    if company and company.summary_review and (
            company.summary_review.status != 'complete' or not company.summary_pages):
        raise ValueError('PowerPoint requires complete, visible introductory Summary coverage')
