"""Readable PDF rendering for the evidence-grounded Markdown report."""

from __future__ import annotations

import io
import re
from hashlib import sha256
from html import escape
from pathlib import Path
from threading import RLock
from typing import Any

from adaptive_document_agent.models import PipelineResult


_FONT_LOCK = RLock()


def build_report_pdf(result: PipelineResult) -> bytes:
    """Render the generated Markdown report as a paginated, Unicode PDF."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover - deployment configuration failure
        raise RuntimeError("PDF export requires reportlab.") from exc

    public_markdown = "\n".join(_public_report_lines(result.report_markdown))
    font_name = _register_report_font(public_markdown)

    stream = io.BytesIO()
    document = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4),
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=result.report_plan.title,
        author="Adaptive Document Intelligence Agent",
    )
    sample = getSampleStyleSheet()
    styles = {
        "h1": ParagraphStyle("ReportTitle", parent=sample["Title"], fontName=font_name, fontSize=24, leading=30, textColor=colors.HexColor("#142442"), alignment=TA_LEFT, spaceAfter=12),
        "h2": ParagraphStyle("Section", parent=sample["Heading2"], fontName=font_name, fontSize=16, leading=21, textColor=colors.HexColor("#0874E8"), spaceBefore=10, spaceAfter=7),
        "h3": ParagraphStyle("Subsection", parent=sample["Heading3"], fontName=font_name, fontSize=12, leading=16, textColor=colors.HexColor("#1B2A41"), spaceBefore=7, spaceAfter=4),
        "body": ParagraphStyle("Body", parent=sample["BodyText"], fontName=font_name, fontSize=9.5, leading=14, textColor=colors.HexColor("#1B2A41"), spaceAfter=5),
        "bullet": ParagraphStyle("Bullet", parent=sample["BodyText"], fontName=font_name, fontSize=9.5, leading=14, leftIndent=12, firstLineIndent=-8, textColor=colors.HexColor("#1B2A41"), spaceAfter=3),
        "table": ParagraphStyle("TableCell", parent=sample["BodyText"], fontName=font_name, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#1B2A41"), alignment=TA_LEFT),
        "table_header": ParagraphStyle("TableHeader", parent=sample["BodyText"], fontName=font_name, fontSize=7.5, leading=9.5, textColor=colors.white, alignment=TA_LEFT),
    }

    story: list[Any] = []
    lines = public_markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("|") and index + 1 < len(lines) and _is_separator_row(lines[index + 1]):
            raw_rows = [_table_cells(line)]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                raw_rows.append(_table_cells(lines[index]))
                index += 1
            column_count = max(len(row) for row in raw_rows)
            rows = [row + [""] * (column_count - len(row)) for row in raw_rows]
            formatted = [
                [Paragraph(_inline(cell), styles["table_header"] if row_index == 0 else styles["table"]) for cell in row]
                for row_index, row in enumerate(rows)
            ]
            table = Table(formatted, colWidths=[document.width / column_count] * column_count, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#142442")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8D6CA")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F2EA")]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.extend([table, Spacer(1, 7)])
            continue
        if not line:
            story.append(Spacer(1, 3))
        elif line.startswith("### "):
            story.append(Paragraph(_inline(line[4:]), styles["h3"]))
        elif line.startswith("## "):
            story.append(Paragraph(_inline(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            story.append(Paragraph(_inline(line[2:]), styles["h1"]))
        elif line.startswith("- "):
            story.append(Paragraph("• " + _inline(line[2:]), styles["bullet"]))
        else:
            story.append(Paragraph(_inline(line), styles["body"]))
        index += 1

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#617083"))
        canvas.drawString(16 * mm, 8 * mm, "Adaptive Document Intelligence Agent")
        canvas.drawRightString(281 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


def _inline(value: str) -> str:
    clean = value.replace("—", "-").replace("–", "-").replace("×", "x")
    escaped = escape(clean)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def _public_report_lines(markdown: str) -> list[str]:
    """Remove technical diagnostics from the formal PDF while retaining limitations."""
    output: list[str] = []
    skipping_validation_section = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.casefold() == "## validation warnings":
            skipping_validation_section = True
            continue
        if skipping_validation_section and line.startswith("## "):
            skipping_validation_section = False
        if skipping_validation_section:
            continue
        if re.match(r"^-\s*\[(?:error|warning|info)\]\s+", line, flags=re.IGNORECASE):
            continue
        output.append(raw_line)
    return output


def _table_cells(value: str) -> list[str]:
    return [cell.strip().replace("\\|", "|") for cell in value.strip().strip("|").split("|")]


def _is_separator_row(value: str) -> bool:
    cells = _table_cells(value)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _register_report_font(content: str) -> str:
    # ReportLab's registry is process-global, including across Streamlit sessions.
    with _FONT_LOCK:
        return _select_report_font(content)


def _select_report_font(content: str) -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont, TTFError

    cjk_chars = set(re.findall(r"[\u3000-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]", content))
    contains_cjk = bool(cjk_chars)
    cjk_candidates = [
        (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/msyhbd.ttc")),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"), Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf")),
        (Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")),
    ]
    latin_candidates = [
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    ]
    # Never substitute a Latin-only font for Chinese just because it loads.
    candidates = cjk_candidates if contains_cjk else [*latin_candidates, *cjk_candidates]
    for regular, bold in candidates:
        if not regular.is_file():
            continue
        font_name = "AdaptiveReport_" + sha256(str(regular).encode()).hexdigest()[:16]
        bold_name = font_name + "Bold"
        registered = pdfmetrics.getRegisteredFontNames()
        try:
            regular_font = (pdfmetrics.getFont(font_name) if font_name in registered
                            else TTFont(font_name, str(regular), subfontIndex=0))
        except (TTFError, OSError):
            # TTC/OTF extensions do not imply TrueType outlines: Noto CJK
            # packages commonly contain CFF/PostScript faces unsupported here.
            continue
        if any(not regular_font.face.charToGlyph.get(ord(char)) for char in cjk_chars):
            continue
        try:
            bold_font = (pdfmetrics.getFont(bold_name) if bold_name in registered
                         else TTFont(bold_name, str(bold), subfontIndex=0))
            if any(not bold_font.face.charToGlyph.get(ord(char)) for char in cjk_chars):
                bold_font = regular_font
        except (TTFError, OSError):
            bold_font = regular_font
        # Publish only a complete usable family; a bad bold face cannot leave a
        # half-registered family that breaks later sessions.
        pdfmetrics.registerFont(regular_font)
        pdfmetrics.registerFont(bold_font)
        pdfmetrics.registerFontFamily(font_name, normal=font_name, bold=bold_font.fontName,
                                      italic=font_name, boldItalic=bold_font.fontName)
        return font_name
    if contains_cjk:
        # Last-resort standard CID fonts preserve CJK text but are not embedded.
        font_name = ("HYSMyeongJo-Medium" if re.search(r"[\uac00-\ud7af]", content)
                     else "HeiseiMin-W3" if re.search(r"[\u3040-\u30ff]", content)
                     else "STSong-Light")
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
            pdfmetrics.registerFontFamily(font_name, normal=font_name, bold=font_name, italic=font_name, boldItalic=font_name)
        return font_name
    return "Helvetica"
