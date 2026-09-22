"""Generic structured company profile extractor.

Extracts structured issuer fields (name, industry, core products, business model,
markets/geographies, market position/ranking, listing/offering facts, headquarters,
reporting currency, track record period) from document profile, text excerpts,
and discovered profile pages across appropriate document sections before slide generation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from adaptive_document_agent.models.presentation import CompanyFact, CompanyProfile
from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery

if TYPE_CHECKING:
    from adaptive_document_agent.models import PipelineResult


_GENERIC_NAMES = {
    "company overview",
    "document overview",
    "document at a glance",
    "company at a glance",
    "document",
    "prospectus",
    "annual report",
    "interim report",
    "financial report",
    "unnamed issuer",
    "company not identified",
    "unnamed company",
    "the company",
    "the group",
    "our company",
    "our group",
    "issuer",
    "issuer profile",
    "executive summary",
    "overview",
    "summary",
}

_GENERIC_PLACEHOLDERS = {
    "document-grounded analysis of reported business operations.",
    "core commercial activities and reported operating model.",
    "key product and service lines as disclosed in documentation.",
    "multi-regional market footprint with commercial presence.",
    "not stated",
    "not disclosed",
    "not clearly disclosed in selected source pages",
    "n/a",
    "none",
    "unknown",
    "various",
    "tbd",
}

_NAVIGATION_ARTIFACT_PATTERNS = [
    re.compile(r"(?i)^(?:table\s+of\s+)?contents\b"),
    re.compile(r"(?i)^page\s+\d+\b"),
    re.compile(r"(?i)^section\s+\d+\b"),
    re.compile(r"(?i)^chapter\s+\d+\b"),
    re.compile(r"(?i)continued\s+on\s+next\s+page"),
    re.compile(r"(?i)^see\s+accompanying\s+notes\b"),
    re.compile(r"(?i)^refer\s+to\s+page\b"),
    re.compile(r"(?i)^forward-looking\s+statements\b"),
    re.compile(r"(?i)^all\s+rights\s+reserved\b"),
    re.compile(r"(?i)^(?:financial\s+information|directors\s+and\s+senior\s+management|definitions|glossary\s+of\s+technical\s+terms|summary\s+of\s+financial\s+data|risk\s+factors)$"),
]

_COMMON_INDUSTRIES = [
    "Biotechnology",
    "Pharmaceuticals",
    "Healthcare",
    "Automotive & Electric Vehicles",
    "Semiconductors & Hardware",
    "Software & Cloud Services",
    "Artificial Intelligence",
    "Consumer Electronics",
    "E-Commerce & Retail",
    "Renewable Energy & Cleantech",
    "Financial Services & Fintech",
    "Industrial Automation",
    "Telecommunications",
    "Real Estate & Property Management",
    "Logistics & Supply Chain",
    "Media & Entertainment",
    "Consumer Goods & Food",
    "Materials & Chemicals",
]

_COMMON_MARKETS = [
    "Mainland China",
    "Hong Kong",
    "North America",
    "United States",
    "Europe",
    "Southeast Asia",
    "Asia-Pacific",
    "Japan",
    "Global Markets",
    "United Kingdom",
    "Germany",
    "Latin America",
    "Middle East",
]

_VALID_STOCK_EXCHANGES = [
    "HKEX",
    "Main Board",
    "NASDAQ",
    "NYSE",
    "SSE",
    "SZSE",
    "SGX",
    "LSE",
    "TSX",
    "ASX",
]


def is_generic_name(name: str) -> bool:
    """Check whether a candidate company name is a placeholder or generic label."""
    cleaned = (name or "").strip().casefold()
    if not cleaned or len(cleaned) < 3:
        return True
    if cleaned in _GENERIC_NAMES:
        return True
    if re.fullmatch(r"(?:group|company|holdings|corp\.?)(?:\s+co\.?,?)?\s+(?:ltd\.?|limited)", cleaned):
        return True
    if any(p in cleaned for p in ("unnamed issuer", "company not identified", "unnamed company", "issuer unknown")):
        return True
    if re.search(r"\bunnamed\s+(?:[\w-]+\s+){0,3}(?:company|issuer)\b", cleaned):
        return True
    if re.match(r"(?i)^(?:the\s+)?(?:company|group|issuer|corporation|prospectus|annual report|overview)$", cleaned):
        return True
    return False


def is_company_identity_resolved(company: CompanyProfile | None) -> bool:
    """Authoritative test for whether the company identity is resolved and evidenced."""
    if company is None:
        return False
    name = (company.name or "").strip()
    if not name or is_generic_name(name):
        return False
    if getattr(company, "identity_state", "") == "UNRESOLVED":
        return False
    return True


# -----------------------------------------------------------------------------
# Field-Level Validators
# -----------------------------------------------------------------------------

def _clean_text_fragment(val: str) -> str:
    """Strip edge punctuation, bullets, hanging connectors, and normalize spacing."""
    s = val.strip().strip("•-* \t\r\n'\"`")
    # Balance unclosed brackets/parentheses
    if s.count("(") > s.count(")"):
        s = re.sub(r"\s*\([^)]*$", "", s)
    if s.count(")") > s.count("("):
        s = re.sub(r"^[^(]*\)\s*", "", s)
    # Strip hanging ellipsis and trailing punctuation
    s = re.sub(r"\.{2,}$", "", s).strip(" ,;:-–—")
    if s.endswith(".") and not re.search(r"(?i)\b(?:Ltd|Inc|Corp|Co|Pte)\.$", s):
        s = s.rstrip(".")
    # Strip dangling trailing conjunctions/prepositions/connectors
    dangling_suffix_pattern = re.compile(
        r"(?i)\s+(?:to|of|and|with|from|in|for|by|as|at|or|the|a|an|including|such\s+as|as\s+well\s+as)$"
    )
    for _ in range(3):
        prev = s
        s = dangling_suffix_pattern.sub("", s).strip(" ,;:-–—")
        if s.endswith(".") and not re.search(r"(?i)\b(?:Ltd|Inc|Corp|Co|Pte)\.$", s):
            s = s.rstrip(".")
        if s == prev:
            break
    # Normalize multiple whitespaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _has_broken_prefix(value: str) -> bool:
    """Detect common extraction fragments such as ``d excerpts`` or ``ing services``."""
    # Keep this case-sensitive and conservative: ordinary sentence starts such
    # as "An international ..." and "No material ..." are valid prose.
    return bool(re.match(r"^(?:[a-z]|ing|ed|tion|ment|ly|al|ic)\s+[a-z]{3,}", value))


def validate_company_name(name: str) -> str:
    """Validate company/issuer legal name."""
    s = _clean_text_fragment(name)
    if not s or len(s) < 3 or len(s) > 100:
        return ""
    if is_generic_name(s):
        return ""
    # Reject navigation artifacts
    for pat in _NAVIGATION_ARTIFACT_PATTERNS:
        if pat.search(s):
            return ""
    # Reject leading single-letter broken fragment like "d excerpts" or "s company"
    if _has_broken_prefix(s):
        return ""
    # Reject hanging prefix conjunctions
    s = re.sub(r"(?i)^(?:and|or|of|the|in|to|with|for|by|including)\s+", "", s).strip()
    if not s or len(s) < 3:
        return ""
    # Must have at least 2 alphanumeric characters and not be pure digits
    if not re.search(r"[A-Za-z\u4e00-\u9fa5]", s) or s.isdigit():
        return ""
    return s


def validate_product(product: str) -> str:
    """Validate a single product/offering string, rejecting fragments and placeholders."""
    s = _clean_text_fragment(product)
    if not s or len(s) < 4 or len(s) > 90:
        return ""
    # Reject generic placeholders
    if s.casefold() in _GENERIC_PLACEHOLDERS or s.casefold() in _GENERIC_NAMES:
        return ""
    # Reject navigation artifacts
    for pat in _NAVIGATION_ARTIFACT_PATTERNS:
        if pat.search(s):
            return ""
    # Reject leading single-letter broken word or truncated prefix like "d excerpts", "s products", "ing solutions", "ed services"
    if _has_broken_prefix(s):
        return ""
    # Strip hanging prefix conjunctions/verbs like "and ", "or ", "including ", "provides "
    s = re.sub(r"(?i)^(?:and|or|of|the|in|to|with|for|by|including|consisting\s+of|provides?|operates?|develops?|delivers?)\s+", "", s).strip(" ,;:-")
    # Strip hanging suffix conjunctions/prepositions
    s = re.sub(r"(?i)\s+(?:and|or|of|the|in|to|with|for|by|including|such\s+as|as\s+well\s+as)$", "", s).strip(" ,;:-")
    if not s or len(s) < 4:
        return ""
    # Must contain letters and not be a standalone generic word
    if not re.search(r"[A-Za-z\u4e00-\u9fa5]", s):
        return ""
    if s.casefold() in {"products", "services", "offerings", "solutions", "excerpts", "others", "various", "general", "including", "and", "or", "the", "development", "manufacturing", "production", "commercialization"}:
        return ""
    if re.search(r"(?i)\b(?:applied for listing|listed on|stock exchange|publicly.listed)\b", s):
        return ""
    return s


def validate_industry(industry: str) -> str:
    """Validate industry sector name."""
    s = _clean_text_fragment(industry)
    if not s or len(s) < 3 or len(s) > 60:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    # Reject standalone generic words lacking sector identity
    if s.casefold() in {"industry", "sector", "business", "general", "services", "company", "group", "operations"}:
        return ""
    for pat in _NAVIGATION_ARTIFACT_PATTERNS:
        if pat.search(s):
            return ""
    if _has_broken_prefix(s):
        return ""
    return s.title() if not s.isupper() else s


def validate_business_model(bm: str) -> str:
    """Validate business model text."""
    s = _clean_text_fragment(bm)
    if not s or len(s) < 5 or len(s) > 220:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    for pat in _NAVIGATION_ARTIFACT_PATTERNS:
        if pat.search(s):
            return ""
    if _has_broken_prefix(s):
        return ""
    # Strip leading phrases like "business model is ", "operates as a "
    s = re.sub(r"(?i)^(?:the\s+)?(?:business\s+model\s+(?:is|consists\s+of)?|operates\s+(?:as\s+an?|through\s+an?))\s*", "", s).strip()
    if not s or len(s) < 5:
        return ""
    return s[0].upper() + s[1:]


def validate_geography(geo: str) -> str:
    """Validate market or geography entry."""
    s = _clean_text_fragment(geo)
    if not s or len(s) < 2 or len(s) > 60:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    if s.casefold() in {"markets", "geographies", "regions", "countries", "presence", "various", "key markets"}:
        return ""
    for pat in _NAVIGATION_ARTIFACT_PATTERNS:
        if pat.search(s):
            return ""
    if _has_broken_prefix(s):
        return ""
    return s.title() if not s.isupper() else s


def validate_market_position(pos: str) -> str:
    """Validate market position or ranking claim."""
    s = _clean_text_fragment(pos)
    if not s or len(s) < 6 or len(s) > 160:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    for pat in _NAVIGATION_ARTIFACT_PATTERNS:
        if pat.search(s):
            return ""
    if _has_broken_prefix(s):
        return ""
    # Must express a ranking, share, or leadership claim
    if not re.search(r"(?i)\b(?:rank|ranked|top\s+\d+|leading|largest|#\d+|no\.?\s*\d+|market\s+share|\d+(?:\.\d+)?%)\b", s):
        return ""
    return s[0].upper() + s[1:]


def validate_stock_code(code: str) -> str:
    """Validate ticker / stock code format."""
    s = _clean_text_fragment(code).upper()
    if not s or len(s) < 2 or len(s) > 12:
        return ""
    if s.casefold() in {"none", "n/a", "tbd", "code", "stock", "unknown", "null"}:
        return ""
    # Must match typical ticker/code patterns
    valid_patterns = [
        re.compile(r"^\d{4,5}(?:\.HK)?$"),
        re.compile(r"^\d{6}(?:\.(?:SZ|SH))?$"),
        re.compile(r"^[A-Z]{1,5}(?::[A-Z]{2,4})?$"),
        re.compile(r"^[A-Z]{2,6}$"),
    ]
    if any(pat.match(s) for pat in valid_patterns):
        return s
    return ""


def validate_listing_market(market: str) -> str:
    """Validate stock exchange / listing market."""
    s = _clean_text_fragment(market)
    if not s or len(s) < 3 or len(s) > 40:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    if re.search(r"(?i)\b(?:application|for listing|on the stock exchange)\b", s):
        return ""
    for ex in _VALID_STOCK_EXCHANGES:
        if re.search(rf"(?i)\b{re.escape(ex)}\b", s):
            return ex.upper() if ex != "Main Board" else "Main Board"
    if re.search(r"(?i)\b(?:stock\s+exchange|exchange)\b", s):
        return s.title()
    return ""


def validate_offering_type(offering: str) -> str:
    """Validate offering / transaction type."""
    s = _clean_text_fragment(offering)
    if not s or len(s) < 3 or len(s) > 50:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    for pat in _NAVIGATION_ARTIFACT_PATTERNS:
        if pat.search(s):
            return ""
    offering_types = ["Main Board IPO", "Initial Public Offering", "Global Offering", "Rights Issue", "Secondary Offering", "IPO"]
    for ot in offering_types:
        if re.search(rf"(?i)\b{re.escape(ot)}\b", s):
            return s if len(s) <= 30 else ot
    return s.title()


def validate_track_record_period(period: str) -> str:
    """Validate track record period text."""
    raw = (period or "").strip()
    # Reject incomplete periods ending in dangling conjunctions/prepositions/hyphens
    if re.search(r"(?i)(?:\b(?:to|from|through|and)|[–—-])\s*[.,;:]*$", raw):
        return ""
    s = _clean_text_fragment(period)
    if not s or len(s) < 4 or len(s) > 60:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    # Reject incomplete ranges ending in dangling words
    if re.search(r"(?i)\b(?:to|from|through|and|–|-)$", s):
        return ""
    # Must contain year pattern or period descriptor
    if not re.search(r"(?i)\b(?:20\d{2}|19\d{2}|FY\s*\d{2,4}|three\s+years|period)\b", s):
        return ""
    # Open-ended range markers are not complete track-record periods.
    has_range_marker = bool(re.search(r"(?i)\b(?:from|to|through)\b|[–—-]", s))
    years = re.findall(r"(?i)\b(?:FY\s*)?(?:19|20)\d{2}\b", s)
    if has_range_marker and len(years) < 2:
        return ""
    return s


def validate_headquarters(hq: str) -> str:
    """Validate headquarters location."""
    s = _clean_text_fragment(hq)
    if not s or len(s) < 3 or len(s) > 60:
        return ""
    if s.casefold() in _GENERIC_PLACEHOLDERS:
        return ""
    if re.match(r"(?i)^(?:[a-z]\s+[a-z]{3,}|(?:ed|in|located\s+in)\s+)", s):
        return ""
    return s.title()


def validate_reporting_currency(curr: str) -> str:
    """Validate reporting currency symbol/code."""
    s = _clean_text_fragment(curr).upper()
    if not s or len(s) > 10:
        return ""
    valid_currencies = {"RMB", "USD", "HKD", "EUR", "GBP", "JPY", "CNY", "SGD", "AUD", "CAD", "$", "¥", "€", "£"}
    for c in valid_currencies:
        if c in s:
            return c
    return s


# -----------------------------------------------------------------------------
# Main Extraction & Population Engine
# -----------------------------------------------------------------------------

def extract_structured_company_fields(
    company: CompanyProfile,
    result: PipelineResult,
) -> CompanyProfile:
    """Extract and populate structured fields from dedicated profile pages and profile metadata.

    Guarantees that Company Overview slides can be built from clean structured cards
    with strict field-level validation and accurate per-field source page citations.
    """
    profile = result.profile
    doc = result.document

    field_source_pages: dict[str, list[int]] = dict(getattr(company, "field_source_pages", {}) or {})

    # Discover and rank company-profile pages across the whole document
    profile_page_texts: list[tuple[int, str]] = []
    if doc and doc.pages:
        profile_page_texts = CompanyProfileDiscovery.get_profile_page_texts(doc, profile, max_pages=8)

    # Base text sources with known or inferred page attribution
    discovered_sources: list[tuple[int, str]] = []
    for p_num, p_text in profile_page_texts:
        discovered_sources.append((p_num, p_text))

    # If no discovered pages, fall back to profile summary/purpose on page 1
    if not discovered_sources:
        summary_page = profile.document_summary_pages[0] if (profile and profile.document_summary_pages) else 1
        summary_text = f"{company.one_line_description}\n{profile.document_summary}\n{profile.document_purpose}\n{profile.overview_title}"
        discovered_sources.append((summary_page, summary_text))

    # -------------------------------------------------------------------------
    # 1. Company / Issuer Legal Name
    # -------------------------------------------------------------------------
    from .company_evidence import cover_name, issuer_windows, supported_field
    cover = cover_name(discovered_sources)
    name = validate_company_name(cover[0]) if cover else validate_company_name(company.name)
    if cover and name:
        field_source_pages["name"] = [cover[1]]
    if not name and profile:
        # Check profile overview title
        cand = validate_company_name(profile.overview_title)
        if cand and not re.search(r"(?i)\boverview\b", cand):
            name = cand
            field_source_pages.setdefault("name", []).extend(profile.document_summary_pages or [1])

    if not name:
        line_name_pattern = re.compile(
            r"\b([A-Z][A-Za-z0-9&.,' -]{2,60}?\s+(?:Co\.,?\s*Ltd|Pte\.?\s*Ltd|Holdings\s+Limited|Holdings\s+Ltd|Limited|Corporation|Corp|Incorporated|Inc|Holdings|Group|Ltd)\.?)(?:\s|$|[,\n])"
        )
        for p_num, p_text in issuer_windows(discovered_sources, name):
            candidates = []
            for line in p_text.splitlines():
                line_clean = line.strip()
                if not line_clean:
                    continue
                line_clean = re.sub(
                    r"(?i)^(?:global\s+offering\s+)?(?:prospectus|annual\s+report|interim\s+report|company\s+overview|corporate\s+overview|company\s+profile|private\s+company\s+profile|business\s+overview)\s*[:\n-]*\s*",
                    "",
                    line_clean,
                ).strip()
                match = line_name_pattern.fullmatch(line_clean)
                if match:
                    cand = validate_company_name(match.group(1).strip(" ,;"))
                    if cand:
                        candidates.append(cand)
            if len(set(candidates)) == 1:
                name = candidates[0]
                field_source_pages["name"] = [p_num]
            if name:
                break

    is_resolved = bool(name and not is_generic_name(name))
    identity_state = "RESOLVED" if is_resolved else "UNRESOLVED"
    final_name = name or ""
    discovered_sources = issuer_windows(discovered_sources, final_name)
    # Revalidate cited model fields against the same entity-bound windows.
    updates = {}
    for field in ("headquarters", "industry", "market_position", "listing_market"):
        value = getattr(company, field, "")
        pages = field_source_pages.get(field, [])
        if field == "headquarters" and value and doc and doc.pages and not pages:
            pages = company.source_pages or [page for page, _ in discovered_sources]
        if value and pages and not supported_field(value, pages, discovered_sources):
            updates[field] = ""
            field_source_pages.pop(field, None)
    company = company.model_copy(update=updates)

    # -------------------------------------------------------------------------
    # 2. Industry
    # -------------------------------------------------------------------------
    industry = validate_industry(company.industry)
    if not industry:
        ind_regex = re.compile(
            r"(?i)\b(?:in the|operating in the|provider in the|focused on the)\s+([A-Za-z0-9\s&-]{3,35}?)\s+(?:industry|sector|space)\b"
        )
        for p_num, p_text in discovered_sources:
            ind_match = ind_regex.search(p_text)
            if ind_match:
                cand = validate_industry(ind_match.group(1))
                if cand:
                    industry = cand
                    field_source_pages.setdefault("industry", []).append(p_num)
                    break
            for ind in _COMMON_INDUSTRIES:
                if re.search(rf"(?i)\b{re.escape(ind)}\b", p_text):
                    industry = ind
                    field_source_pages.setdefault("industry", []).append(p_num)
                    break
            if industry:
                break

    # -------------------------------------------------------------------------
    # 3. Core Products / Services
    # -------------------------------------------------------------------------
    existing_products = [validate_product(p) for p in company.products]
    products = [p for p in existing_products if p]
    if not products:
        prod_regex = re.compile(
            r"(?i)\b(?:core products?|products and services|main offerings|offerings include|specializ(?:es|ing|ed)?\s+in|develops and sells|\bprovides?\b)\s*(?::|include[s]?|consisting of)?\s*([^.;\n]{5,180})"
        )
        for p_num, p_text in discovered_sources:
            for prod_match in prod_regex.finditer(p_text):
                raw_prods = re.split(r"[,;]|\band\b", prod_match.group(1))
                for raw in raw_prods:
                    vp = validate_product(raw)
                    if vp and vp not in products:
                        products.append(vp)
            if products:
                field_source_pages.setdefault("products", []).append(p_num)
                break
        # If still empty, check segments
        if not products and company.segments:
            for s in company.segments:
                vs = validate_product(s)
                if vs and vs not in products:
                    products.append(vs)

    # -------------------------------------------------------------------------
    # 4. Business Model
    # -------------------------------------------------------------------------
    business_model = validate_business_model(company.business_model)
    if not business_model:
        bm_regex = re.compile(
            r"(?i)(?:business model|monetization|revenue model|revenue is primarily derived from|generates revenue through|operates\s+(?:an?))\s*(?::|is|through)?\s*([^;\n]+?)(?:\.\s|\.$|;\s*|\n|$)"
        )
        for p_num, p_text in discovered_sources:
            bm_match = bm_regex.search(p_text)
            if bm_match:
                cand = validate_business_model(bm_match.group(1))
                if cand:
                    business_model = cand
                    field_source_pages.setdefault("business_model", []).append(p_num)
                    break
            # Common model keywords
            found_models: list[str] = []
            if re.search(r"(?i)\bB2B\b", p_text):
                found_models.append("B2B enterprise solutions")
            if re.search(r"(?i)\bB2C\b", p_text):
                found_models.append("B2C consumer products")
            if re.search(r"(?i)\bSaaS\b|subscription", p_text):
                found_models.append("Subscription / recurring model")
            if re.search(r"(?i)\bdirect\s+sales\b", p_text):
                found_models.append("Direct sales model")
            if re.search(r"(?i)\bdistributor(?:s|\s+network)?\b", p_text):
                found_models.append("Distributor network sales")
            if re.search(r"(?i)\bcontract\s+manufacturing|OEM|ODM\b", p_text):
                found_models.append("Contract manufacturing / OEM")
            if found_models:
                business_model = "; ".join(found_models)
                field_source_pages.setdefault("business_model", []).append(p_num)
                break

    # -------------------------------------------------------------------------
    # 5. Main Markets / Geographies
    # -------------------------------------------------------------------------
    existing_geos = [validate_geography(g) for g in company.geographies]
    geographies = [g for g in existing_geos if g]
    if not geographies:
        geo_regex = re.compile(
            r"(?i)(?:main|principal|key|primary|target)\s+markets?|geographic presence|geographic markets?|key regions?|operations in\b"
        )
        for p_num, p_text in discovered_sources:
            geo_match = geo_regex.search(p_text)
            if geo_match:
                after_text = p_text[geo_match.end():geo_match.end() + 200]
                sub_snippet = re.split(r"[.;\n]", after_text)[0]
                sub_snippet = re.sub(r"(?i)^(?::|include[s]?|primarily in|primarily|across)?\s*", "", sub_snippet)
                raw_geos = re.split(r"[,;]|\band\b", sub_snippet)
                for raw in raw_geos:
                    vg = validate_geography(raw)
                    if vg and vg not in geographies:
                        geographies.append(vg)
                for m in _COMMON_MARKETS:
                    if re.search(rf"(?i)\b{re.escape(m)}\b", sub_snippet) and m not in geographies:
                        geographies.append(m)
                if geographies:
                    field_source_pages.setdefault("geographies", []).append(p_num)
                    break

    # -------------------------------------------------------------------------
    # 6. Customer Types
    # -------------------------------------------------------------------------
    customer_types = list(company.customer_types)
    if not customer_types:
        cust_regex = re.compile(
            r"(?i)(?:target customers?|customer base|clients include|end users?|serving)\s*(?::|include[s]?|primarily)?\s*([^.;\n]{5,120})"
        )
        for p_num, p_text in discovered_sources:
            cust_match = cust_regex.search(p_text)
            if cust_match:
                raw_custs = re.split(r"[,;]|\band\b", cust_match.group(1))
                for rc in raw_custs:
                    vc = _clean_text_fragment(rc)
                    if vc and len(vc) >= 3 and vc.casefold() not in _GENERIC_PLACEHOLDERS:
                        customer_types.append(vc)
                if customer_types:
                    field_source_pages.setdefault("customer_types", []).append(p_num)
                    break

    # -------------------------------------------------------------------------
    # 7. Market Position / Ranking
    # -------------------------------------------------------------------------
    market_position = validate_market_position(getattr(company, "market_position", ""))
    if not market_position:
        rank_pattern = re.compile(
            r"(?i)\b((?:ranked\s+(?:no\.?\s*\d+|#\d+|\w+)|top\s+\d+|leading\s+provider|largest\s+[\w\s-]+\s+in|(?:holds?\s+(?:an?\s+)?|with\s+(?:an?\s+)?)?[\d.]+(?:%|\s*percent)\s+market\s+share[^;\n]*?|market\s+share\s+(?:with|of|is)\s+[\d.]+%|[\w\s-]*market\s+share\s+(?:with|of)\s+[\d.]+%)[^;\n]*?)(?<!\bNo)(?:\.(?:\s+[A-Z]|\s*$)|;|\n|$)"
        )
        for p_num, p_text in discovered_sources:
            rank_match = rank_pattern.search(p_text)
            if rank_match:
                cand = validate_market_position(rank_match.group(1))
                if cand:
                    market_position = cand
                    field_source_pages.setdefault("market_position", []).append(p_num)
                    break

    # -------------------------------------------------------------------------
    # 8. Listing & Offering Facts (Exchange, Stock Code, Offering Type)
    # -------------------------------------------------------------------------
    stock_code = validate_stock_code(company.stock_code)
    if not stock_code:
        code_regexes = [
            re.compile(r"(?i)\b(?:stock\s*code|ticker|ticker\s*symbol):\s*([0-9A-Za-z.]{2,10})\b"),
            re.compile(r"\b(\d{4,5}\.HK|\d{6}\.(?:SZ|SH)|[A-Z]{1,5}:[A-Z]{2,4})\b"),
        ]
        for p_num, p_text in discovered_sources:
            for pat in code_regexes:
                match = pat.search(p_text)
                if match:
                    cand = validate_stock_code(match.group(1))
                    if cand:
                        stock_code = cand
                        field_source_pages.setdefault("stock_code", []).append(p_num)
                        break
            if stock_code:
                break

    listing_market = validate_listing_market(company.listing_market)
    if not listing_market:
        exchange_patterns = [
            re.compile(r"(?i)\b(HKEX|Main\s+Board|NASDAQ|NYSE|SSE|SZSE|SGX|LSE|TSX|ASX)\b"),
            re.compile(r"(?i)\b([A-Za-z\s]{3,30}Stock\s+Exchange)\b"),
        ]
        for p_num, p_text in discovered_sources:
            for pat in exchange_patterns:
                m = pat.search(p_text)
                if m:
                    cand = validate_listing_market(m.group(1))
                    if cand:
                        listing_market = cand
                        field_source_pages.setdefault("listing_market", []).append(p_num)
                        break
            if listing_market:
                break

    offering_type = validate_offering_type(company.offering_type)
    if not offering_type:
        offering_patterns = [
            re.compile(r"(?i)\b(IPO|Initial\s+Public\s+Offering|Global\s+Offering|Rights\s+Issue|Secondary\s+Offering)\b"),
        ]
        for p_num, p_text in discovered_sources:
            for pat in offering_patterns:
                m = pat.search(p_text)
                if m:
                    cand = validate_offering_type(m.group(1))
                    if cand:
                        offering_type = cand
                        field_source_pages.setdefault("offering_type", []).append(p_num)
                        break
            if offering_type:
                break

    track_record = validate_track_record_period(company.track_record_period)
    if not track_record:
        tr_regexes = [
            re.compile(r"(?i)\b(?:track\s+record\s+period|review\s+period):\s*([^\n;.]+)\b"),
            re.compile(r"\b(FY\s*20\d{2}\s*[-–to ]+\s*FY\s*20\d{2}|20\d{2}\s*[-–to ]+\s*20\d{2})\b"),
        ]
        for p_num, p_text in discovered_sources:
            for pat in tr_regexes:
                match = pat.search(p_text)
                if match:
                    cand = validate_track_record_period(match.group(1))
                    if cand:
                        track_record = cand
                        field_source_pages.setdefault("track_record_period", []).append(p_num)
                        break
            if track_record:
                break

    headquarters = validate_headquarters(company.headquarters)
    if not headquarters:
        hq_regex = re.compile(
            r"(?i)\b(?:headquarters?|headquartered|head\s+office|registered\s+office|principal\s+place\s+of\s+business)\b\s*(?::|is\s+in|in|located\s+in)?\s*([A-Za-z ,.-]{3,45}?)(?:\.\s|\.$|;\s*|\n|$)"
        )
        for p_num, p_text in discovered_sources:
            hq_match = hq_regex.search(p_text)
            if hq_match:
                cand = validate_headquarters(hq_match.group(1))
                if cand:
                    headquarters = cand
                    field_source_pages.setdefault("headquarters", []).append(p_num)
                    break

    profile_curr = getattr(profile, "currency", "") or (profile.currencies[0] if (profile and getattr(profile, "currencies", None)) else "")
    reporting_currency = validate_reporting_currency(company.reporting_currency or profile_curr)
    if not reporting_currency:
        curr_regex = re.compile(r"(?i)\b(?:reporting\s+currency|presentation\s+currency|currency)\s*:\s*([A-Za-z$¥€£]{1,10})\b")
        for p_num, p_text in discovered_sources:
            cm = curr_regex.search(p_text)
            if cm:
                cand = validate_reporting_currency(cm.group(1))
                if cand:
                    reporting_currency = cand
                    field_source_pages.setdefault("reporting_currency", []).append(p_num)
                    break

    listing_facts: list[str] = [f for f in getattr(company, "listing_facts", []) if f and f.casefold() not in _GENERIC_PLACEHOLDERS]
    if not listing_facts:
        if stock_code:
            listing_facts.append(f"Stock Code: {stock_code}")
        if listing_market:
            listing_facts.append(f"Exchange: {listing_market}")
        if offering_type:
            listing_facts.append(f"Offering Type: {offering_type}")
        if track_record:
            listing_facts.append(f"Track Record: {track_record}")

    # Deduplicate per-field source pages
    clean_field_source_pages: dict[str, list[int]] = {}
    for k, v in field_source_pages.items():
        clean_field_source_pages[k] = sorted(set(v))

    # Inherit source pages
    all_cited_pages = set(company.source_pages)
    for p_list in clean_field_source_pages.values():
        all_cited_pages.update(p_list)
    for fact in company.key_facts:
        all_cited_pages.update(fact.source_pages)

    if not all_cited_pages:
        all_cited_pages = set(p_num for p_num, _ in discovered_sources)

    company_pages = sorted(all_cited_pages)[:8]

    # Preserve existing valid key facts
    facts = list(company.key_facts)

    return company.model_copy(
        update={
            "name": final_name,
            "industry": industry,
            "headquarters": headquarters,
            "reporting_currency": reporting_currency,
            "products": products[:6],
            "business_model": business_model,
            "customer_types": customer_types[:6],
            "geographies": geographies[:6],
            "market_position": market_position,
            "stock_code": stock_code,
            "listing_market": listing_market,
            "offering_type": offering_type,
            "track_record_period": track_record,
            "listing_facts": listing_facts[:6],
            "identity_state": identity_state,
            "key_facts": facts[:8],
            "source_pages": company_pages,
            "field_source_pages": clean_field_source_pages,
        }
    )
