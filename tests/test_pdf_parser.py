"""PDF validation and page-level parsing tests."""

import fitz
import pytest

from adaptive_document_agent.extraction.pdf_parser import PDFParser, PDFValidationError


def make_pdf(text: str = "Revenue 2025 was 1250.") -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_parse_preserves_page_text_and_hash() -> None:
    parsed = PDFParser().parse(make_pdf())
    assert parsed.page_count == 1
    assert "Revenue" in parsed.pages[0].text
    assert len(parsed.sha256) == 64
    assert parsed.safe_filename.startswith("document_")


@pytest.mark.parametrize("value", [b"", b"not a pdf"])
def test_invalid_pdf_fails_safely(value: bytes) -> None:
    with pytest.raises(PDFValidationError):
        PDFParser().parse(value)


def test_image_only_page_is_marked_for_ocr() -> None:
    document = fitz.open()
    page = document.new_page()
    pixmap = fitz.Pixmap(fitz.csRGB, (0, 0, 100, 100), 0)
    pixmap.clear_with(255)
    page.insert_image((0, 0, 100, 100), pixmap=pixmap)
    parsed = PDFParser().parse(document.tobytes())
    document.close()
    assert parsed.pages[0].requires_ocr is True
    assert "OCR is required" in parsed.pages[0].warnings[0]

