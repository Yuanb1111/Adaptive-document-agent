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
]


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

        selected: list[int] = []
        for _, page_num in scored_pages:
            if page_num not in selected:
                selected.append(page_num)
            if len(selected) >= max_pages:
                break

        # Always include page 1 if not present and document has pages
        if 1 not in selected and document.page_count >= 1:
            selected.insert(0, 1)

        return sorted(selected[:max_pages])

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
