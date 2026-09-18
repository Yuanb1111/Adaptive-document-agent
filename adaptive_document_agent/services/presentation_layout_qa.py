"""Presentation layout quality assurance service.

Validates layout geometry, detects text clipping, font shrinkage, mechanical ellipses,
and crowded slides across generated PowerPoint decks.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class LayoutQAIssue(BaseModel):
    slide_index: int
    issue_type: str
    message: str
    severity: str = "warning"  # "warning" or "critical"


class PresentationLayoutQA:
    """Automated presentation layout QA analyzer."""

    def __init__(self, presentation: Any) -> None:
        self.presentation = presentation

    def validate(self) -> list[LayoutQAIssue]:
        issues: list[LayoutQAIssue] = []
        for idx, slide in enumerate(self.presentation.slides):
            issues.extend(self._check_slide(idx, slide))
        return issues

    def _check_slide(self, idx: int, slide: Any) -> list[LayoutQAIssue]:
        issues: list[LayoutQAIssue] = []
        text_char_count = 0
        card_count = 0
        content_boxes: list[tuple[float, float, float, float]] = []

        for shape in slide.shapes:
            left = getattr(shape, "left", None)
            top = getattr(shape, "top", None)
            width = getattr(shape, "width", None)
            height = getattr(shape, "height", None)

            # 1. Slide bounds overflow check (13.33in x 7.50in standard widescreen)
            if left and width:
                l_in = left.inches
                w_in = width.inches
                if l_in + w_in > 13.10:
                    issues.append(
                        LayoutQAIssue(
                            slide_index=idx,
                            issue_type="horizontal_overflow",
                            message=f"Shape '{shape.name}' overflows right margin (x={l_in + w_in:.2f}in > 13.10in)",
                            severity="warning",
                        )
                    )
            if top and height:
                t_in = top.inches
                h_in = height.inches
                # Allow footer zone down to 7.20in
                if t_in + h_in > 7.30 and idx > 0:
                    issues.append(
                        LayoutQAIssue(
                            slide_index=idx,
                            issue_type="vertical_overflow",
                            message=f"Shape '{shape.name}' overflows bottom margin (y={t_in + h_in:.2f}in > 7.30in)",
                            severity="warning",
                        )
                    )

            # 2. Text checks: font shrinkage, mechanical ellipses, character counts
            if shape.has_text_frame:
                frame = shape.text_frame
                for p in frame.paragraphs:
                    p_text = p.text.strip()
                    if not p_text:
                        continue
                    text_char_count += len(p_text)

                    # Check mechanical ellipsis in titles / short headings
                    if len(p_text) < 80 and (p_text.endswith("...") or p_text.endswith("…")):
                        issues.append(
                            LayoutQAIssue(
                                slide_index=idx,
                                issue_type="mechanical_ellipsis",
                                message=f"Heading or label ends with mechanical ellipsis: '{p_text}'",
                                severity="warning",
                            )
                        )

                    # Check font shrinkage
                    if p.font and p.font.size:
                        pt_size = p.font.size.pt
                        # Tiny font check (below 8.0pt on content paragraphs, excluding page numbers)
                        if pt_size < 8.0 and not p_text.startswith("p. ") and not p_text.startswith("Source pages"):
                            issues.append(
                                LayoutQAIssue(
                                    slide_index=idx,
                                    issue_type="font_shrinkage",
                                    message=f"Font size {pt_size:.1f}pt is below minimum readable 8.0pt threshold in: '{p_text[:40]}'",
                                    severity="warning",
                                )
                            )

            # Count KPI / content panels
            if hasattr(shape, "shape_type") and shape.name.startswith("Rectangle"):
                if top and top.inches > 1.30:
                    card_count += 1

        # 3. Slide density check
        if card_count > 10:
            issues.append(
                LayoutQAIssue(
                    slide_index=idx,
                    issue_type="crowded_slide_cards",
                    message=f"Slide contains {card_count} cards, exceeding recommended maximum of 8-10 cards",
                    severity="warning",
                )
            )
        if text_char_count > 1200:
            issues.append(
                LayoutQAIssue(
                    slide_index=idx,
                    issue_type="excessive_text_density",
                    message=f"Slide contains {text_char_count} characters, which may impair presentation legibility",
                    severity="warning",
                )
            )

        return issues
