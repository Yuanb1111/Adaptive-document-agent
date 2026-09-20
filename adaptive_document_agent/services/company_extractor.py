"""Generic structured company profile extractor.

Extracts structured issuer fields (name, industry, core products, business model,
markets/geographies, market position/ranking, listing/offering facts) from
document profile, text excerpts, and observations before slide generation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from adaptive_document_agent.models.presentation import CompanyFact, CompanyProfile

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
}

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
]


def extract_structured_company_fields(
    company: CompanyProfile,
    result: PipelineResult,
) -> CompanyProfile:
    """Extract and populate structured fields from document profile and excerpts.
    
    Guarantees that Company Overview slides can be built from clean structured cards
    rather than falling back to an unstructured narrative paragraph.
    """
    profile = result.profile
    doc = result.document

    # Gather source texts for extraction
    text_sources: list[str] = [
        company.one_line_description,
        profile.document_summary,
        profile.document_purpose,
        profile.overview_title,
    ]
    # Include first few page excerpts if available
    if doc and doc.pages:
        for p in doc.pages[:5]:
            if p.text:
                text_sources.append(p.text[:1000])

    combined_text = "\n".join(t.strip() for t in text_sources if t and t.strip())

    # 1. Company / Issuer Name
    name = company.name.strip()
    is_unresolved = (
        not name
        or name.casefold() in _GENERIC_NAMES
        or bool(re.search(r"(?i)\b(?:unnamed\s+issuer|company\s+not\s+identified)\b", name))
    )

    if is_unresolved:
        # Check profile overview title
        cand = profile.overview_title.strip() if profile.overview_title else ""
        if cand and cand.casefold() not in _GENERIC_NAMES and not re.search(r"(?i)\boverview\b", cand):
            name = cand
            is_unresolved = False
        else:
            # Try to detect company name pattern e.g. "XYZ Co., Ltd." or "ABC Inc."
            name_match = re.search(
                r"\b([A-Z][A-Za-z0-9&.,\s]{2,45}\s+(?:Limited|Ltd\.?|Corporation|Corp\.?|Inc\.?|Holdings|Group|Co\.,?\s*Ltd\.?))\b",
                combined_text,
            )
            if name_match:
                extracted = name_match.group(1).strip(" ,.")
                if extracted.casefold() not in _GENERIC_NAMES and len(extracted) > 3:
                    name = extracted
                    is_unresolved = False

    identity_state = "UNRESOLVED" if is_unresolved else ("RESOLVED" if company.identity_state == "RESOLVED" or name else "PARTIALLY_RESOLVED")

    # 2. Industry
    industry = company.industry.strip()
    if not industry:
        ind_match = re.search(
            r"(?i)\b(?:in the|operating in the|provider in the|focused on the)\s+([A-Za-z0-9\s&-]{3,35}?)\s+(?:industry|sector|space)\b",
            combined_text,
        )
        if ind_match:
            industry = ind_match.group(1).strip().title()
        else:
            for ind in _COMMON_INDUSTRIES:
                if re.search(rf"(?i)\b{re.escape(ind)}\b", combined_text):
                    industry = ind
                    break

    # 3. Core Products / Services
    products = list(company.products)
    if not products:
        prod_match = re.search(
            r"(?i)(?:core products?|products and services|main offerings|offerings include|specializ(?:es|ing|ed)?\s+in|develops and sells|provides?)\s*(?::|include[s]?|consisting of)?\s*([^.;\n]{5,180})",
            combined_text,
        )
        if prod_match:
            raw_prods = re.split(r"[,;]|\band\b", prod_match.group(1))
            cleaned = [p.strip().strip("-•* ") for p in raw_prods if len(p.strip()) > 3]
            products = cleaned[:6]
        elif company.segments:
            products = list(company.segments[:6])

    # 4. Business Model
    business_model = company.business_model.strip()
    if not business_model:
        bm_match = re.search(
            r"(?i)(?:business model|monetization|revenue model|revenue is primarily derived from|generates revenue through|operates\s+(?:an?))\s*(?::|is|through)?\s*([^;\n]+?)(?:\.\s|\.$|;\s*|\n|$)",
            combined_text,
        )
        if bm_match:
            business_model = bm_match.group(1).strip().capitalize()
        else:
            # Look for common models
            found_models: list[str] = []
            if re.search(r"(?i)\bB2B\b", combined_text):
                found_models.append("B2B enterprise solutions")
            if re.search(r"(?i)\bB2C\b", combined_text):
                found_models.append("B2C consumer products")
            if re.search(r"(?i)\bSaaS\b|subscription", combined_text):
                found_models.append("Subscription / recurring model")
            if re.search(r"(?i)\bdirect\s+sales\b", combined_text):
                found_models.append("Direct sales model")
            if re.search(r"(?i)\bdistributor(?:s|\s+network)?\b", combined_text):
                found_models.append("Distributor network sales")
            if re.search(r"(?i)\bcontract\s+manufacturing|OEM|ODM\b", combined_text):
                found_models.append("Contract manufacturing / OEM")
            if found_models:
                business_model = "; ".join(found_models)

    # 5. Main Markets / Geographies
    geographies = list(company.geographies)
    if not geographies:
        geo_match = re.search(
            r"(?i)(?:main markets?|geographic presence|geographic markets?|key regions?|operations in)\s*(?::|include[s]?|primarily in)?\s*([^.;\n]{5,120})",
            combined_text,
        )
        if geo_match:
            raw_geos = re.split(r"[,;]|\band\b", geo_match.group(1))
            geographies = [g.strip().strip("-•* ") for g in raw_geos if len(g.strip()) > 2][:6]
        else:
            found_geos = [m for m in _COMMON_MARKETS if re.search(rf"(?i)\b{re.escape(m)}\b", combined_text)]
            if found_geos:
                geographies = found_geos[:6]

    # 6. Market Position / Ranking
    market_position = getattr(company, "market_position", "").strip()
    if not market_position:
        rank_pattern = re.compile(
            r"(?i)\b((?:ranked\s+(?:no\.?\s*\d+|#\d+|\w+)|top\s+\d+|leading\s+provider|largest\s+[\w\s-]+\s+in|(?:holds?\s+(?:an?\s+)?|with\s+(?:an?\s+)?)?[\d.]+(?:%|\s*percent)\s+market\s+share[^;\n]*?|market\s+share\s+(?:with|of|is)\s+[\d.]+%|[\w\s-]*market\s+share\s+(?:with|of)\s+[\d.]+%)[^;\n]*?)(?:\.\s|\.$|;\s*|\n|$)"
        )
        for src in text_sources:
            if not src:
                continue
            rank_match = rank_pattern.search(src)
            if rank_match:
                market_position = rank_match.group(1).strip().capitalize()
                break

    # 7. Listing / Offering Facts
    stock_code = company.stock_code.strip()
    if not stock_code:
        code_match = re.search(r"(?i)\b(?:stock\s*code|ticker|ticker\s*symbol):\s*([0-9A-Za-z.]{2,10})\b", combined_text)
        if not code_match:
            code_match = re.search(r"\b(\d{4,5}\.HK|\d{6}\.(?:SZ|SH)|[A-Z]{1,5}:[A-Z]{2,4})\b", combined_text)
        if code_match:
            stock_code = code_match.group(1).strip()

    listing_market = company.listing_market.strip()
    if not listing_market:
        market_match = re.search(r"(?i)\b(HKEX|Main\s+Board|NASDAQ|NYSE|SSE|SZSE|SGX|LSE)\b", combined_text)
        if market_match:
            listing_market = market_match.group(1).upper()

    offering_type = company.offering_type.strip()
    if not offering_type:
        offering_match = re.search(r"(?i)\b(IPO|Initial\s+Public\s+Offering|Global\s+Offering|Rights\s+Issue)\b", combined_text)
        if offering_match:
            offering_type = offering_match.group(1).title()

    track_record = company.track_record_period.strip()
    if not track_record:
        tr_match = re.search(r"(?i)\b(?:track\s+record\s+period|review\s+period):\s*([^\n;.]+)\b", combined_text)
        if not tr_match:
            tr_match = re.search(r"\b(FY\s*20\d{2}\s*[-–to ]+\s*FY\s*20\d{2}|20\d{2}\s*[-–to ]+\s*20\d{2})\b", combined_text)
        if tr_match:
            track_record = tr_match.group(1).strip()

    listing_facts: list[str] = list(getattr(company, "listing_facts", []))
    if not listing_facts:
        if stock_code:
            listing_facts.append(f"Stock Code: {stock_code}")
        if listing_market:
            listing_facts.append(f"Exchange: {listing_market}")
        if offering_type:
            listing_facts.append(f"Offering Type: {offering_type}")
        if track_record:
            listing_facts.append(f"Track Record: {track_record}")

    # Inherit source pages if empty
    company_pages = list(company.source_pages) or list(profile.document_summary_pages) or ([1] if doc and doc.page_count else [])

    # Preserve existing key facts
    facts = list(company.key_facts)

    return company.model_copy(
        update={
            "name": name,
            "industry": industry,
            "products": products[:6],
            "business_model": business_model,
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
        }
    )
