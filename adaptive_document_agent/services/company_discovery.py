"""Dedicated company-profile discovery across document sections.

Ranks pages for company overview, business, products, markets, and listing
information separately from financial analysis pages.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adaptive_document_agent.models import DocumentProfile, ParsedDocument


_PROFILE_HEADINGS = [
    re.compile(r"(?i)\b(?:company|corporate|business)\s+overview\b"),
    re.compile(r"(?i)\b(?:company|corporate)\s+profile\b"),
    re.compile(r"(?i)\bour\s+business\b"),
    re.compile(r"(?i)\bbusiness\s+summary\b"),
    re.compile(r"(?i)\babout\s+(?:us|the\s+company|the\s+group)\b"),
    re.compile(r"(?i)\bcorporate\s+information\b"),
    re.compile(r"(?i)\bproducts?\s+and\s+services\b"),
    re.compile(r"(?i)\b(?:core|principal|main)\s+products?\b"),
    re.compile(r"(?i)\bbusiness\s+model\b"),
    re.compile(r"(?i)\bcompetitive\s+strengths\b"),
    re.compile(r"(?i)\b(?:principal|geographic)\s+markets?\b"),
    re.compile(r"(?i)\bglobal\s+offering\b"),
    re.compile(r"(?i)\bhistory\s+and\s+corporate\s+structure\b"),
    re.compile(r"(?i)\bindustry\s+overview\b"),
]

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "profile": [
        "company overview",
        "company profile",
        "business overview",
        "our business",
        "about us",
        "corporate information",
        "who we are",
        "about the company",
        "is a leading",
        "is a provider",
        "operates as a",
    ],
    "products": [
        "core products",
        "products and services",
        "main offerings",
        "principal products",
        "product portfolio",
        "specializes in",
        "offerings include",
        "solutions include",
        "pipeline",
        "commercialized products",
    ],
    "business_model": [
        "business model",
        "revenue model",
        "monetization",
        "b2b",
        "b2c",
        "subscription model",
        "direct sales",
        "distributor network",
        "contract manufacturing",
        "oem",
        "commercial operations",
    ],
    "customers": [
        "target customers",
        "customer base",
        "clients include",
        "end users",
        "customer types",
        "institutional clients",
        "enterprise customers",
        "key accounts",
    ],
    "markets_position": [
        "principal markets",
        "geographic presence",
        "key markets",
        "market position",
        "market share",
        "ranked no.",
        "ranked #",
        "leading provider",
        "largest provider",
        "competitive strengths",
        "competitive advantages",
        "industry ranking",
    ],
    "listing_offering": [
        "global offering",
        "stock code",
        "ticker",
        "initial public offering",
        "ipo",
        "hkex",
        "main board",
        "nyse",
        "nasdaq",
        "offering type",
        "stock exchange",
        "listing exchange",
    ],
    "identity_meta": [
        "headquarters",
        "registered office",
        "head office",
        "principal place of business",
        "reporting currency",
        "track record period",
        "review period",
        "incorporation",
    ],
}

_FINANCIAL_STATEMENT_PHRASES = [
    "consolidated statement of financial position",
    "consolidated balance sheet",
    "consolidated statement of profit or loss",
    "consolidated statement of comprehensive income",
    "consolidated statement of cash flows",
    "notes to the consolidated financial statements",
    "independent auditor's report",
    "accountant's report",
    "statutory financial statements",
    "financial information",
]

_ISSUER_OVERVIEW = re.compile(
    r"(?i)\b(?:we\s+are|our\s+(?:products?|cobots?|solutions?|sales\s+network|customers?))\b"
)
_BUSINESS_SUBSTANCE = re.compile(
    r"(?i)\b(?:develop\w*|manufactur\w*|commercializ\w*|"
    r"product\s+(?:portfolio|series|range)|customer\s+base|direct\s+sales|distributors?)\b"
)
_ADMINISTRATIVE_CONTENT = re.compile(
    r"(?i)\b(?:documents?\s+delivered\s+to\s+the\s+registrar|"
    r"application\s+for\s+listing|underwriting|shareholders?\s+general\s+meeting|"
    r"over-allocation|disclosure\s+of\s+interests)\b"
)
_RISK_DISCLOSURE = re.compile(
    r"(?i)\b(?:risk\s+factors|risks?\s+and\s+uncertainties|"
    r"materially\s+and\s+adversely\s+affect|we\s+cannot\s+assure\s+you)\b"
)


class CompanyProfileDiscovery:
    """Discovers and ranks candidate company-profile pages across the whole document."""

    @classmethod
    def score_page(cls, page_text: str, page_number: int, total_pages: int) -> float:
        """Score a single page for company-profile evidence relevance."""
        if not page_text or not page_text.strip():
            return 0.0

        text_lower = page_text.casefold()
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        heading_candidate = " ".join(lines[:6]) if lines else ""

        score = 0.0

        # 1. Base bonus for document cover and introductory pages
        if page_number == 1:
            score += 5.0
        elif page_number == 2:
            score += 3.0
        elif page_number <= min(5, total_pages):
            score += 1.5

        # 2. Heading inspection
        for pattern in _PROFILE_HEADINGS:
            if pattern.search(heading_candidate):
                score += 8.0
                break

        # A page about the issuer's operations is more useful than a page
        # that merely repeats listing terminology or names other companies.
        has_issuer_business = bool(
            _ISSUER_OVERVIEW.search(page_text[:1_600])
            and _BUSINESS_SUBSTANCE.search(page_text[:1_600])
        )
        overview_heading = re.search(
            r"(?im)^\s*(?:business\s+overview|our\s+business|overview)\s*$",
            page_text[:1_800],
        )
        if overview_heading and has_issuer_business:
            score += 18.0
        elif has_issuer_business and re.search(r"(?i)^\s*(?:our\s+history|business\s+summary)", page_text):
            score += 10.0

        # 3. Category keyword scoring with per-category caps
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            cat_matches = 0
            for kw in keywords:
                if kw in text_lower:
                    cat_matches += 1
            if cat_matches > 0:
                # Diminishing returns: reward presence of multiple diverse categories
                score += min(cat_matches, 3) * 2.0

        # 4. Financial statement penalty
        # If the page is primarily an accounting statement or dense audit note, downweight
        is_financial_statement = any(phrase in text_lower for phrase in _FINANCIAL_STATEMENT_PHRASES)
        if is_financial_statement:
            num_digits = sum(c.isdigit() for c in page_text)
            if num_digits > 200 or len(lines) > 40:
                score -= 10.0

        if _ADMINISTRATIVE_CONTENT.search(heading_candidate):
            score -= 8.0
        if _RISK_DISCLOSURE.search(page_text[:1_000]) and not overview_heading:
            score -= 15.0

        return max(score, 0.0)

    @classmethod
    def rank_profile_pages(
        cls,
        document: ParsedDocument,
        profile: DocumentProfile | None = None,
        max_pages: int = 8,
    ) -> list[int]:
        """Return the top ranked page numbers for company-profile extraction."""
        if not document or not document.pages:
            return []

        scored_pages: list[tuple[float, int]] = []
        for page in document.pages:
            s = cls.score_page(page.text, page.page_number, document.page_count)
            # Extra boost if document summary previously cited this page
            if profile and page.page_number in profile.document_summary_pages:
                s += 3.0
            if s > 0.0:
                scored_pages.append((s, page.page_number))

        scored_pages.sort(key=lambda item: (item[0], -item[1]), reverse=True)

        page_by_number = {page.page_number: page for page in document.pages}
        selected: list[int] = []
        if 1 in page_by_number:
            selected.append(1)

        # A substantive overview frequently continues into the next pages.
        # Retain that context before filling the budget with isolated keyword
        # hits from risk, listing, or accounting sections.
        anchors = []
        for _, page_num in scored_pages:
            text = page_by_number[page_num].text
            if re.match(r"(?i)^\s*(?:our\s+history|history\s+and\s+corporate)", text):
                continue
            if re.search(r"(?im)^\s*(?:business\s+overview|our\s+business|overview)\s*$", text[:1_800]):
                if _ISSUER_OVERVIEW.search(text[:1_600]) and _BUSINESS_SUBSTANCE.search(text[:1_600]):
                    anchors.append(page_num)
            if len(anchors) >= 2:
                break
        for anchor in anchors:
            for page_num in range(anchor, anchor + 3):
                if page_num in page_by_number and page_num not in selected and len(selected) < max_pages:
                    selected.append(page_num)

        for _, page_num in scored_pages:
            if page_num not in selected and len(selected) < max_pages:
                selected.append(page_num)
        return sorted(selected)

    @classmethod
    def get_profile_page_texts(
        cls,
        document: ParsedDocument,
        profile: DocumentProfile | None = None,
        max_pages: int = 8,
    ) -> list[tuple[int, str]]:
        """Return (page_number, page_text) pairs for the top ranked company profile pages."""
        ranked_pages = cls.rank_profile_pages(document, profile, max_pages=max_pages)
        page_by_num = {p.page_number: p.text for p in document.pages}
        return [(p_num, page_by_num[p_num]) for p_num in ranked_pages if p_num in page_by_num and page_by_num[p_num].strip()]
