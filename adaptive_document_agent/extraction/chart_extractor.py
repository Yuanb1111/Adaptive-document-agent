"""Initial chart interface marks image candidates for optional vision analysis."""

from adaptive_document_agent.models.page import DocumentPage, PageImage

from .image_extractor import vision_candidates


class ChartExtractor:
    def candidates(self, pages: list[DocumentPage]) -> list[PageImage]:
        return [image for page in pages for image in vision_candidates(page.images)]

