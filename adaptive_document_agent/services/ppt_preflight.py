"""Pre-export presentation quality control, collision detection, and preflight sanitization."""

from __future__ import annotations

import re
from typing import Any

# Forbidden internal/debug phrases that must never appear in client-facing decks
BANNED_PHRASES = (
    "calculated result",
    "calculated change result",
    "based on extracted observations",
    "this is a calculated result",
    "internal calculation",
    "debug",
    "parser",
    "extracted observations",
    "generated metric",
    "retained fact",
    "ai says",
    "llm",
    "json",
)


class PreflightIssue:
    def __init__(self, slide_idx: int, check: str, message: str, severity: str = "warning"):
        self.slide_idx = slide_idx
        self.check = check
        self.code = check
        self.message = message
        self.severity = severity

    def __repr__(self) -> str:
        return f"Slide {self.slide_idx + 1} [{self.check}] ({self.severity}): {self.message}"


class PresentationPreflight:
    """Automated pre-export validation for PowerPoint presentations."""

    def __init__(self, presentation: Any):
        self.presentation = presentation
        self.issues: list[PreflightIssue] = []

    def validate_and_sanitize(self) -> list[PreflightIssue]:
        self.issues.clear()
        for idx, slide in enumerate(self.presentation.slides):
            self._check_chart_gridlines(idx, slide)
            self._check_banned_phrases(idx, slide)
            self._check_collisions(idx, slide)
        return self.issues

    def _check_chart_gridlines(self, idx: int, slide: Any) -> None:
        for shape in slide.shapes:
            if shape.has_chart:
                chart = shape.chart
                # Enforce no horizontal background gridlines
                try:
                    if hasattr(chart, "value_axis") and chart.value_axis is not None:
                        if chart.value_axis.has_major_gridlines:
                            chart.value_axis.has_major_gridlines = False
                            self.issues.append(PreflightIssue(idx, "chart_gridlines", "Disabled horizontal major gridlines on chart"))
                        if chart.value_axis.has_minor_gridlines:
                            chart.value_axis.has_minor_gridlines = False
                except Exception:
                    pass

    def _check_banned_phrases(self, idx: int, slide: Any) -> None:
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text
                text_lower = text.casefold()
                for phrase in BANNED_PHRASES:
                    if phrase in text_lower:
                        self.issues.append(PreflightIssue(idx, "banned_phrase", f"Found banned phrase '{phrase}' in text"))
                        # Sanitize in place if possible
                        self._sanitize_text_frame(shape.text_frame, phrase)

    @staticmethod
    def _sanitize_text_frame(frame: Any, phrase: str) -> None:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        for p in frame.paragraphs:
            if pattern.search(p.text):
                # Clean professional rephrasing
                if phrase in ("calculated result", "calculated change result", "this is a calculated result"):
                    p.text = pattern.sub("Analysis indicates", p.text)
                elif phrase in ("based on extracted observations", "extracted observations"):
                    p.text = pattern.sub("based on reported disclosures", p.text)
                else:
                    p.text = pattern.sub("", p.text)

    def _check_collisions(self, idx: int, slide: Any) -> None:
        layout_name = slide.slide_layout.name if hasattr(slide, "slide_layout") else ""
        is_two_line = "Two-line" in layout_name or "2-line" in layout_name
        content_min_top = 1.65 if is_two_line else 1.38

        # In non-cover, non-divider slides: content shapes should not encroach above content_min_top
        if "封面" in layout_name or "短文本" in layout_name or idx == 0:
            return

        for shape in slide.shapes:
            # Skip placeholders 14, 15, 16 (titles/subtitles)
            if getattr(shape, "is_placeholder", False):
                try:
                    if shape.placeholder_format.idx in (14, 15, 16):
                        continue
                except Exception:
                    pass
            # Skip shapes that are clearly slide number / watermarks at bottom
            top = shape.top.inches if hasattr(shape, "top") else 0
            if top < content_min_top and top > 0.1:
                self.issues.append(
                    PreflightIssue(
                        idx,
                        "title_collision",
                        f"Shape '{shape.name}' at top={top:.2f}in encroaches on title/subtitle zone (min={content_min_top:.2f}in)",
                        severity="warning",
                    )
                )
