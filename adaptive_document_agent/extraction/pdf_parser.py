"""Safe page-level PDF validation and orchestration."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import BinaryIO

from adaptive_document_agent.models import DocumentPage, PageImage, ParsedDocument
from adaptive_document_agent.utils.ids import stable_id

from .table_extractor import TableExtractor


class PDFValidationError(ValueError):
    """Raised for invalid or unreadable PDF input without leaking internals."""


class PDFParser:
    def __init__(self, *, min_text_characters: int = 30, max_upload_mb: int = 200) -> None:
        self.min_text_characters = min_text_characters
        self.max_bytes = max_upload_mb * 1024 * 1024
        self.table_extractor = TableExtractor()

    def parse(
        self,
        source: bytes | bytearray | str | Path | BinaryIO,
        *,
        filename: str | None = None,
        extract_tables: bool = True,
        table_pages: set[int] | None = None,
    ) -> ParsedDocument:
        data, supplied_name = self._read_bytes(source)
        filename = filename or supplied_name or "uploaded.pdf"
        self._validate_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        document_id = stable_id("document", digest)
        safe_name = f"{document_id}.pdf"

        try:
            import pymupdf as fitz

            pdf = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise PDFValidationError("The uploaded file is not a readable PDF.") from exc

        try:
            if pdf.needs_pass:
                return ParsedDocument(
                    document_id=document_id,
                    sha256=digest,
                    safe_filename=safe_name,
                    page_count=pdf.page_count,
                    encrypted=True,
                    warnings=["The PDF is encrypted and requires a password."],
                )
            if pdf.page_count == 0:
                raise PDFValidationError("The PDF contains no pages.")
            pages = [self._parse_page(page, number) for number, page in enumerate(pdf, start=1)]
        finally:
            pdf.close()

        if extract_tables:
            tables_by_page = self.table_extractor.extract(data, page_numbers=table_pages)
            for page in pages:
                page.tables = tables_by_page.get(page.page_number, [])
        warnings = [warning for page in pages for warning in page.warnings]
        return ParsedDocument(
            document_id=document_id,
            sha256=digest,
            safe_filename=safe_name,
            page_count=len(pages),
            pages=pages,
            warnings=warnings,
        )

    def _parse_page(self, page: object, page_number: int) -> DocumentPage:
        text = page.get_text("text", sort=True) or ""  # type: ignore[attr-defined]
        raw_blocks = page.get_text("blocks", sort=True) or []  # type: ignore[attr-defined]
        blocks = [
            {"bbox": tuple(float(v) for v in block[:4]), "text": str(block[4]), "block_number": int(block[5])}
            for block in raw_blocks
            if len(block) >= 6
        ]
        images: list[PageImage] = []
        for index, image in enumerate(page.get_images(full=True)):  # type: ignore[attr-defined]
            width = int(image[2]) if len(image) > 2 else None
            height = int(image[3]) if len(image) > 3 else None
            images.append(
                PageImage(
                    image_id=stable_id("image", page_number, index, image[0]),
                    page=page_number,
                    width=width,
                    height=height,
                )
            )
        printable = sum(character.isalnum() for character in text)
        requires_ocr = printable < self.min_text_characters and bool(images)
        quality = min(1.0, printable / max(self.min_text_characters * 4, 1))
        if printable >= self.min_text_characters:
            quality = max(0.7, quality)
        warnings = [f"OCR is required for page {page_number} but no OCR engine is configured."] if requires_ocr else []
        return DocumentPage(
            page_number=page_number,
            text=text,
            images=images,
            extraction_quality=quality,
            requires_ocr=requires_ocr,
            text_blocks=blocks,
            warnings=warnings,
        )

    def _read_bytes(self, source: bytes | bytearray | str | Path | BinaryIO) -> tuple[bytes, str | None]:
        if isinstance(source, (bytes, bytearray)):
            return bytes(source), None
        if isinstance(source, (str, Path)):
            path = Path(source)
            if not path.exists() or not path.is_file():
                raise PDFValidationError("The PDF file does not exist.")
            return path.read_bytes(), path.name
        if not hasattr(source, "read"):
            raise PDFValidationError("Unsupported PDF input.")
        value = source.read()
        if not isinstance(value, bytes):
            raise PDFValidationError("The uploaded file must be binary.")
        return value, Path(getattr(source, "name", "uploaded.pdf")).name

    def _validate_bytes(self, data: bytes) -> None:
        if not data:
            raise PDFValidationError("The uploaded PDF is empty.")
        if len(data) > self.max_bytes:
            raise PDFValidationError(f"The uploaded PDF exceeds the {self.max_bytes // 1024 // 1024} MB limit.")
        if not data.startswith(b"%PDF-"):
            raise PDFValidationError("The uploaded file does not have a valid PDF signature.")
