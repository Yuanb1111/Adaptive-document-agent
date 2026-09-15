"""Image candidate helpers."""

from adaptive_document_agent.models.page import PageImage


def vision_candidates(images: list[PageImage], *, minimum_area: int = 10_000) -> list[PageImage]:
    return [
        image
        for image in images
        if image.requires_vision and (image.width or 0) * (image.height or 0) >= minimum_area
    ]

