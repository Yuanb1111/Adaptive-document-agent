"""First-page source artwork remains local, cited and source-matched."""

import io
from hashlib import sha256

import pymupdf
import pytest
from PIL import Image
from pptx import Presentation

from adaptive_document_agent.models import DocumentPage
from adaptive_document_agent.services.export import _build_cache_key
from adaptive_document_agent.services.pptx_export import build_presentation
from adaptive_document_agent.services.presentation_source_visual import select_company_source_visual
from tests.test_p1_theme_planning import themed_result


def _document_with_image(*, page_text: str, image_rect=(40, 150, 550, 570)):
    image = io.BytesIO()
    Image.new("RGB", (1200, 800), (54, 96, 145)).save(image, format="JPEG")
    pdf = pymupdf.open()
    for _ in range(3):
        pdf.new_page(width=595, height=842)
    pdf[0].insert_text((40, 80), page_text, fontsize=11)
    pdf[0].insert_image(pymupdf.Rect(image_rect), stream=image.getvalue())
    data = pdf.tobytes()
    pdf.close()
    result = themed_result()
    result.document.sha256 = sha256(data).hexdigest()
    result.document.page_count = 3
    result.document.pages = [DocumentPage(page_number=i, text=page_text if i == 1 else "Other content")
                             for i in range(1, 4)]
    result.presentation_plan.company.name = "ACME DEVICES LIMITED"
    result.presentation_plan.company.identity_state = "RESOLVED"
    result.presentation_plan.company.field_source_pages = {"name": [1], "products": [1]}
    return data, result


def test_source_pdf_image_appears_once_on_company_slide_with_page_citation():
    pdf, result = _document_with_image(page_text=(
        "ACME DEVICES LIMITED supplies industrial devices. "
        "Our products include imaging equipment."
    ))
    selected = select_company_source_visual(pdf, result)
    assert selected is not None and selected.page == 1
    assert selected.kind == "embedded_image"
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        # The original asset excludes the separately typeset cover text.
        assert selected.payload == document.extract_image(document[0].get_images()[0][0])["image"]
    assert _build_cache_key(result, "template") != _build_cache_key(result, "template", source_pdf=pdf)

    deck = Presentation(io.BytesIO(build_presentation(result, source_pdf=pdf)))
    sourced = [(slide, shape) for slide in deck.slides for shape in slide.shapes
               if shape.name.startswith("source_document_image:")]
    assert len(sourced) == 1
    slide, shape = sourced[0]
    assert slide.name == "picture_profile" and shape.name == "source_document_image:p1"
    assert not any(item.name == "picture_profile_continued" for item in deck.slides)
    text = " ".join(item.text for item in slide.shapes if item.has_text_frame)
    assert "Image from source document" not in text
    assert "Source: Document disclosures (p. 1" in text
    assert "page 1" in slide.notes_slide.notes_text_frame.text


def test_source_preview_includes_scanned_pages_and_rejects_wrong_pdf():
    pdf, result = _document_with_image(page_text="", image_rect=(40, 150, 80, 190))
    selected = select_company_source_visual(pdf, result)
    assert selected.kind == "page_snapshot"
    with Image.open(io.BytesIO(selected.payload)) as image:
        assert max(image.size) == 1800
        assert image.width / image.height == pytest.approx(595 / 842, abs=.002)
    result.document.sha256 = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        select_company_source_visual(pdf, result)


def test_text_vector_first_page_is_used_even_without_resolved_identity():
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=900)
    page.insert_text((50, 60), "SOURCE COVER")
    page.draw_rect(pymupdf.Rect(40, 40, 560, 860), color=(0.2, 0.1, 0.6))
    data = pdf.tobytes()
    pdf.close()
    result = themed_result()
    result.presentation_plan = None
    result.document.sha256 = sha256(data).hexdigest()
    result.document.page_count = 1
    result.document.pages = [DocumentPage(page_number=1, text="SOURCE COVER")]
    selected = select_company_source_visual(data, result)
    assert selected.page == 1
    assert selected.kind == "page_snapshot"
    with Image.open(io.BytesIO(selected.payload)) as image:
        assert image.size == (1200, 1800)
        assert image.convert("L").getextrema()[0] < 200
    deck = Presentation(io.BytesIO(build_presentation(result, source_pdf=data)))
    pictures = [shape for slide in deck.slides for shape in slide.shapes
                if shape.name == "source_document_image:p1"]
    assert len(pictures) == 1
    assert all(getattr(pictures[0], name) == 0 for name in ("crop_left", "crop_right", "crop_top", "crop_bottom"))


def test_profile_preview_retains_all_copy_and_source_pages():
    from adaptive_document_agent.services.presentation_brief import BriefItem
    from adaptive_document_agent.services.presentation_source_visual import render_profile_with_source
    from adaptive_document_agent.services.pptx_export import DEFAULT_TEMPLATE_PATH
    pdf, result = _document_with_image(page_text="Document description")
    visual = select_company_source_visual(pdf, result)
    deck = Presentation(DEFAULT_TEMPLATE_PATH)
    items = [BriefItem("Overview", "Verified description of the document.", [2]),
             BriefItem("Scope", "Observations cover the explicitly reported period.", [3])]
    slides = render_profile_with_source(deck, "Document overview", items, visual)
    assert len(slides) == 1
    text = " ".join(shape.text for shape in slides[0].shapes if shape.has_text_frame)
    assert all(item.text in text for item in items)
    assert "Source document, p. 1" not in text
    assert "p. 1-3" in text
    assert "analytical claims" in slides[0].notes_slide.notes_text_frame.text


def test_long_profile_preview_paginates_without_hiding_copy():
    from adaptive_document_agent.services.presentation_brief import BriefItem
    from adaptive_document_agent.services.presentation_source_visual import render_profile_with_source
    from adaptive_document_agent.services.pptx_export import DEFAULT_TEMPLATE_PATH
    pdf, result = _document_with_image(page_text="Document description")
    deck = Presentation(DEFAULT_TEMPLATE_PATH)
    items = [BriefItem(f"Point {i}", "A fully sourced and qualified statement. " * 6, [2]) for i in range(6)]
    slides = render_profile_with_source(deck, "Document overview", items, select_company_source_visual(pdf, result))
    assert len(slides) > 1
    text = " ".join(shape.text for slide in slides for shape in slide.shapes if shape.has_text_frame)
    assert all(item.title in text for item in items)
    assert text.count("A fully sourced and qualified statement.") == 36
    assert not any(shape.name == "source_document_image:p1" for slide in slides for shape in slide.shapes)
    assert all(any(shape.has_text_frame and shape.text.strip() not in {"", "Document overview", "Document overview (continued)"}
                   for shape in slide.shapes) for slide in slides)


def test_summary_introduction_no_longer_bypasses_source_preview():
    from adaptive_document_agent.models import PresentationSlide
    from adaptive_document_agent.services.pptx_export import _add_company_at_a_glance
    from tests.test_presentation_identity_contents import _deck, _resolved_result
    pdf, source_result = _document_with_image(page_text="Source cover")
    result = _resolved_result()
    original = result.model_dump()
    deck = _deck()
    deck._ada_source_visual = select_company_source_visual(pdf, source_result)
    _add_company_at_a_glance(deck, result, PresentationSlide(
        id="company", slide_type="company_overview", title="Company overview"))
    assert len(deck.slides) == 2
    assert sum(shape.name == "source_document_image:p1" for slide in deck.slides for shape in slide.shapes) == 1
    first_text = " ".join(shape.text for shape in deck.slides[0].shapes if shape.has_text_frame)
    assert "We operate a business software platform." in first_text
    assert "Source document, p. 1" not in first_text
    assert "Source: Document disclosures (p. 1, 5)" in first_text
    assert result.model_dump() == original
