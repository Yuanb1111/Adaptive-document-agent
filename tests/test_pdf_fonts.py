"""Font compatibility and independent-download regressions for hosted exports."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pytest
from reportlab.pdfbase import pdfmetrics, ttfonts

from adaptive_document_agent.models import DocumentProfile, ParsedDocument, PipelineResult, ReportPlan
from adaptive_document_agent.services.pdf_export import _register_report_font, build_report_pdf
from adaptive_document_agent.ui import exports


def report(markdown: str) -> PipelineResult:
    return PipelineResult(
        document=ParsedDocument(document_id="font-test", sha256="abc", safe_filename="source.pdf", page_count=1),
        profile=DocumentProfile(), report_plan=ReportPlan(title="Report"), report_markdown=markdown,
    )


@pytest.fixture
def font_registry(monkeypatch):
    # Test cold and warm registries without depending on suite order.
    monkeypatch.setattr(pdfmetrics, "_fonts", dict(pdfmetrics._fonts))
    for name in list(pdfmetrics._fonts):
        if name.startswith("AdaptiveReport"):
            del pdfmetrics._fonts[name]
    monkeypatch.setattr(pdfmetrics, "_dynFaceNames", dict(pdfmetrics._dynFaceNames))


@pytest.mark.parametrize("error", [ttfonts.TTFError("postscript outlines are not supported"), OSError("unreadable")])
def test_unusable_cjk_font_falls_back_without_latin_substitution(monkeypatch, font_registry, error):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    constructor = Mock(side_effect=error)
    monkeypatch.setattr(ttfonts, "TTFont", constructor)
    assert _register_report_font("公司收入分析") == "STSong-Light"
    assert constructor.call_count >= 2  # Continue past the first bad candidate.
    assert all("arial" not in str(call) and "DejaVu" not in str(call) for call in constructor.call_args_list)


def test_unsupported_regular_font_tries_next_candidate(monkeypatch, font_registry):
    real_constructor = ttfonts.TTFont
    vera = Path(ttfonts.__file__).parents[1] / "fonts" / "Vera.ttf"
    attempted = []

    def constructor(name, filename, **kwargs):
        attempted.append(filename)
        if "DejaVu" in filename:
            raise ttfonts.TTFError("invalid font")
        return real_constructor(name, str(vera))

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(ttfonts, "TTFont", constructor)
    name = _register_report_font("Revenue")
    assert name.startswith("AdaptiveReport_")
    assert any("arial" in item for item in attempted)


def test_bad_bold_face_uses_regular_and_does_not_poison_family(monkeypatch, font_registry):
    real_constructor = ttfonts.TTFont
    vera = Path(ttfonts.__file__).parents[1] / "fonts" / "Vera.ttf"

    def constructor(name, filename, **kwargs):
        if name.endswith("Bold"):
            raise ttfonts.TTFError("postscript outlines are not supported")
        return real_constructor(name, str(vera))

    constructor.State = real_constructor.State
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(ttfonts, "TTFont", constructor)
    for _ in range(2):
        payload = build_report_pdf(report("# Report\n\n**Revenue** 1,234"))
        with pymupdf.open(stream=payload, filetype="pdf") as pdf:
            assert "Revenue" in pdf[0].get_text()


def test_latin_registration_cannot_override_later_chinese(monkeypatch, font_registry):
    real_constructor = ttfonts.TTFont
    vera = Path(ttfonts.__file__).parents[1] / "fonts" / "Vera.ttf"
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(ttfonts, "TTFont", lambda name, *a, **k: real_constructor(name, str(vera)))
    latin = _register_report_font("Revenue")
    chinese = _register_report_font("公司收入分析")
    assert chinese == "STSong-Light"  # Readable font without required glyphs is rejected.
    assert latin != chinese
    assert _register_report_font("Revenue") == latin


@pytest.mark.parametrize("text, expected", [("English", "Helvetica"), ("中文", "STSong-Light"),
                                           ("日本語かな", "HeiseiMin-W3"), ("한국어", "HYSMyeongJo-Medium")])
def test_no_font_files_has_language_appropriate_fallback(monkeypatch, text, expected):
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert _register_report_font(text) == expected


def test_mixed_chinese_report_survives_rejected_fonts(monkeypatch, font_registry):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(ttfonts, "TTFont", Mock(side_effect=ttfonts.TTFError("unsupported outlines")))
    payload = build_report_pdf(report("# 公司分析 Report\n\n**营业收入** RMB 1,234\n\n"
                                      "| 指标 | 2025 |\n| --- | --- |\n| 收入 | 1,234 |\n"))
    with pymupdf.open(stream=payload, filetype="pdf") as pdf:
        text = "".join(page.get_text() for page in pdf)
        assert "公司分析" in text and "营业收入" in text and "1,234" in text
        assert pdf[0].get_pixmap().width > 0


@pytest.mark.parametrize("failed_format", ["pdf", "markdown", "csv", "json"])
def test_download_failure_is_isolated_and_redacted(monkeypatch, caplog, failed_format):
    st = Mock()
    for kind in ("markdown", "pdf", "csv", "json"):
        exporter = Mock(return_value=b"verified content")
        if kind == failed_format:
            exporter.side_effect = ttfonts.TTFError("private document text and secret path")
        monkeypatch.setattr(exports, "export_" + kind, exporter)
    exports.render_report_downloads(st, report("# Report"), tuple(nullcontext() for _ in range(3)))
    assert st.download_button.call_count == 3
    assert st.button.call_args.kwargs["disabled"] is True
    assert "TTFError" in st.warning.call_args.args[0]
    assert "private document" not in str(st.mock_calls) + caplog.text


def test_linux_production_fonts_embed_chinese(monkeypatch, font_registry):
    import os
    if os.environ.get("PPTX_QA_LIBREOFFICE_INTEGRATION") != "1":
        pytest.skip("Opt-in Linux production font integration")
    noto = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    wqy = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
    assert noto.is_file() and wqy.is_file()
    with pytest.raises(ttfonts.TTFError, match="postscript outlines"):
        ttfonts.TTFont("UnsupportedNotoTest", str(noto), subfontIndex=0)
    _register_report_font("English first")
    name = _register_report_font("公司收入分析")
    assert isinstance(pdfmetrics.getFont(name), ttfonts.TTFont)
    payload = build_report_pdf(report("# 公司收入分析\n\n**营业收入** RMB 1,234\n\n来源：第 1 页"))
    with pymupdf.open(stream=payload, filetype="pdf") as pdf:
        assert "公司收入分析" in pdf[0].get_text()
        assert "营业收入" in pdf[0].get_text()
        assert any(pdf.extract_font(font[0])[3] for font in pdf[0].get_fonts())
        assert pdf[0].get_pixmap().width > 0
