"""Small presentation helpers; no model calls, document decisions, or remote assets."""

from base64 import b64encode
from functools import lru_cache
from html import escape
from pathlib import Path

from adaptive_document_agent.services.fourier_brand import CHART_COLORS as BRAND_CHART_COLORS, PRIMARY

ASSETS = Path(__file__).with_name("assets")
PURPLE = f"#{PRIMARY}"
CHART_COLORS = tuple(f"#{color}" for color in BRAND_CHART_COLORS)
FONT_STACK = 'Roboto, "Source Han Sans CN", "Source Han Sans SC", "Microsoft YaHei", Arial, sans-serif'


@lru_cache(maxsize=1)
def _stylesheet() -> str:
    return (ASSETS / "fourier.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _logo_uri() -> str:
    return "data:image/svg+xml;base64," + b64encode((ASSETS / "fourier-logo.svg").read_bytes()).decode("ascii")


def apply_theme(st) -> None:
    st.markdown(f"<style>{_stylesheet()}</style>", unsafe_allow_html=True)


def sidebar_brand(st) -> None:
    st.markdown(
        f'<div class="fourier-brand"><img src="{_logo_uri()}" alt="FOURIER 傅利叶" />'
        '<a class="fourier-brand-guide" '
        'href="app/static/Adaptive_Document_Agent_Beginner_Guide_Public_2026-09-30.pdf" '
        'aria-label="打开零基础上手手册 PDF">零基础上手手册 ↗</a></div>',
        unsafe_allow_html=True,
    )


def header(st) -> None:
    st.title("Document to PowerPoint")
    st.markdown("Generate an editable presentation with findings and page-level sources.")


def section_label(st, number: str, title: str) -> None:
    st.markdown(
        f'<div class="fourier-section"><span>{escape(number)}</span>'
        f'<h2>{escape(title)}</h2></div>', unsafe_allow_html=True,
    )


def result_heading(st, result) -> None:
    section_label(st, "02", "Your results")
    st.markdown(
        f'<div class="fourier-result-file"><span class="fourier-file-type">PDF</span>'
        f'<span>{escape(result.document.safe_filename)}</span>'
        f'<span class="fourier-file-pages">{result.document.page_count} pages</span></div>',
        unsafe_allow_html=True,
    )


def insight_card(st, insight, number: int) -> None:
    pages = ", ".join(map(str, sorted({source.page for source in insight.evidence})))
    kind = {"reported_fact": "Reported fact", "calculated_result": "Calculated result", "interpretation": "Interpretation"}[insight.kind]
    st.markdown(
        '<article class="fourier-insight">'
        f'<span class="fourier-eyebrow">{number:02d} / {kind}</span>'
        f'<h4>{escape(insight.title)}</h4><p>{escape(insight.narrative)}</p>'
        f'<div class="fourier-small">{escape("Source pages: " + pages if pages else "No page evidence attached")}</div>'
        '</article>', unsafe_allow_html=True,
    )


def style_chart(figure):
    """Apply typography/surfaces without changing any values or source annotations."""
    figure.update_layout(
        font={"family": FONT_STACK, "color": "#000000"},
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", colorway=list(CHART_COLORS),
    )
    figure.update_xaxes(gridcolor="#F6F7F7", zerolinecolor="#DBDCDC")
    figure.update_yaxes(gridcolor="#F6F7F7", zerolinecolor="#DBDCDC")
    return figure
