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
            self._check_semantic_units(idx, slide)
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
        if "封面" in layout_name or "短文本" in layout_name or idx == 0:
            return

        title_ph = None
        sub_ph = None
        for shape in slide.placeholders:
            try:
                if shape.placeholder_format.idx in (14, 15):
                    title_ph = shape
                elif shape.placeholder_format.idx == 16:
                    sub_ph = shape
            except Exception:
                pass

        # 1. Check and correct title-subtitle overlap
        if title_ph and sub_ph and sub_ph.has_text_frame and sub_ph.text.strip():
            title_bottom = title_ph.top.inches + title_ph.height.inches
            if sub_ph.top.inches < title_bottom - 0.02:
                self.issues.append(
                    PreflightIssue(
                        idx,
                        "title_subtitle_collision",
                        f"Subtitle at top={sub_ph.top.inches:.2f}in collides with title ending at {title_bottom:.2f}in",
                        severity="warning",
                    )
                )
                from pptx.util import Inches
                sub_ph.top = Inches(title_bottom + 0.08)

        # 2. Compute dynamic content boundary based on subtitle/title bottom
        content_min_top = 1.38
        if sub_ph and sub_ph.has_text_frame and sub_ph.text.strip():
            content_min_top = max(content_min_top, sub_ph.top.inches + sub_ph.height.inches + 0.06)
        elif title_ph and title_ph.has_text_frame and title_ph.text.strip():
            content_min_top = max(content_min_top, title_ph.top.inches + title_ph.height.inches + 0.06)

        for shape in slide.shapes:
            if getattr(shape, "is_placeholder", False):
                try:
                    if shape.placeholder_format.idx in (14, 15, 16):
                        continue
                except Exception:
                    pass
            top = shape.top.inches if hasattr(shape, "top") else 0
            if 0.2 < top < content_min_top - 0.05:
                self.issues.append(
                    PreflightIssue(
                        idx,
                        "title_collision",
                        f"Shape '{shape.name}' at top={top:.2f}in encroaches on title/subtitle zone (min={content_min_top:.2f}in)",
                        severity="warning",
                    )
                )

    def _check_semantic_units(self, idx: int, slide: Any) -> None:
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text
                # Multiple metrics mistakenly formatted with %
                for match in re.finditer(r"(?i)\b(current ratio|quick ratio)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\s*%", text):
                    self.issues.append(
                        PreflightIssue(
                            idx,
                            "invalid_ratio_unit",
                            f"Ratio metric formatted with percentage: '{match.group(0)}'",
                            severity="warning",
                        )
                    )
                    ratio_val = match.group(2)
                    new_val = f"{match.group(1)}: {ratio_val}x"
                    for p in shape.text_frame.paragraphs:
                        if match.group(0) in p.text:
                            p.text = p.text.replace(match.group(0), new_val)

                # Multiple metrics with pp change (e.g. +0.2 pp)
                for match in re.finditer(r"(?i)\b(current ratio|quick ratio)[^0-9\n]*([+\-][0-9]+(?:\.[0-9]+)?)\s*pp\b", text):
                    self.issues.append(
                        PreflightIssue(
                            idx,
                            "invalid_ratio_change",
                            f"Ratio change formatted with pp: '{match.group(0)}'",
                            severity="warning",
                        )
                    )
                    for p in shape.text_frame.paragraphs:
                        if match.group(0) in p.text:
                            p.text = p.text.replace(f"{match.group(2)} pp", f"{match.group(2)}x")
