"""Select a bounded, cited image from the uploaded PDF for the company slide.

The selected image is contextual artwork, not evidence for a financial claim.
Its source page remains visible in the slide and no PDF content leaves the local
export process.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from adaptive_document_agent.models import PipelineResult

from .presentation_artwork import validate_artwork


@dataclass(frozen=True)
class SourceVisual:
    payload: bytes
    page: int


def select_company_source_visual(pdf_bytes: bytes, result: PipelineResult) -> SourceVisual | None:
    """Return a substantial embedded image on an issuer-profile source page.

    Scanned pages, tiny logos and images on analytical/financial pages are not
    used as stand-ins for product photography. An absent suitable image leaves
    the existing text-only company slide unchanged.
    """
    if sha256(pdf_bytes).hexdigest() != result.document.sha256:
        raise ValueError("The uploaded PDF does not match the analysed document; source image was not embedded.")
    plan = result.presentation_plan
    if plan is None:
        return None
    from .company_extractor import is_company_identity_resolved
    if not is_company_identity_resolved(plan.company):
        return None
    try:
        import pymupdf
    except ImportError:
        return None

    company = plan.company
    cited: list[int] = []
    for field in ("products", "application_areas", "business_model", "name", "one_line_description"):
        cited.extend(company.field_source_pages.get(field, []))
    cited.extend(page for page in company.source_pages if page <= 5)
    # The cover may carry the only usable product photograph, but a text-free
    # scanned first page should never be copied into a slide as an image.
    cited.extend(range(1, min(3, result.document.page_count) + 1))
    pages = list(dict.fromkeys(p for p in cited if 1 <= p <= result.document.page_count))[:12]
    if not pages:
        return None

    best: tuple[float, SourceVisual] | None = None
    source_pages = {item.page_number: item for item in result.document.pages}
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for rank, page_number in enumerate(pages):
            source_page = source_pages.get(page_number)
            if source_page is None or len(source_page.text.strip()) < 40:
                continue
            page = document[page_number - 1]
            heading = source_page.text[:280].casefold()
            if any(label in heading for label in (
                "financial information", "financial statements", "statement of financial position",
                "cash flows", "income statement",
            )):
                continue
            seen_xrefs: set[int] = set()
            for image_info in page.get_images(full=True)[:80]:
                xref = image_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                width, height = image_info[2:4]
                if width < 750 or height < 450 or not 0.45 <= width / height <= 3.2:
                    continue
                image_areas = [((rect & page.rect).get_area() / max(page.rect.get_area(), 1))
                               for rect in page.get_image_rects(xref)]
                area = max(image_areas, default=0)
                if area < 0.12:
                    continue
                image = document.extract_image(xref)
                if image.get("ext") not in {"png", "jpeg", "jpg"}:
                    continue
                try:
                    payload = validate_artwork(image["image"])
                except ValueError:
                    continue
                if payload is None:
                    continue
                score = area + min(width * height / 4_000_000, 1) * 0.2
                score += max(0, len(pages) - rank) * 0.01
                if best is None or score > best[0]:
                    best = (score, SourceVisual(payload=payload, page=page_number))
    return best[1] if best else None
