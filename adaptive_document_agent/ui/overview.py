"""Overview result tab."""

import re

from adaptive_document_agent.models import PipelineResult
from .branding import insight_card


def render(st, result: PipelineResult) -> None:
    from adaptive_document_agent.services.executive_brief import display_brief
    try:
        title, items = display_brief(result)
    except ValueError:
        title = "Executive Summary"
        items = []
        st.warning("The saved executive briefing failed its source checks. Showing document context instead.")
    if items:
        st.subheader(_literal(title))
        for item in items:
            st.markdown(f"**{_literal(item.title)}** — {_literal(item.text)}")
            st.caption("Source pages: " + ", ".join(map(str, item.pages)))
        with st.expander("Document context and analysis coverage", expanded=False):
            _context(st, result)
    else:
        if any(w.code == "executive_brief_unavailable" for w in result.validation_warnings):
            st.caption("The final briefing is unavailable for this run. Document context is shown below.")
        _context(st, result)
    if result.profile.data_quality_notes:
        notes = list(dict.fromkeys(result.profile.data_quality_notes))
        st.warning(
            f"{len(notes)} data-quality note(s) may affect interpretation. "
            "Open the details below or use the Data Quality tab for the full audit."
        )
        with st.expander("Data-quality notes", expanded=False):
            for note in notes:
                st.markdown(f"- {note}")
    if result.insights and not items:
        st.subheader("Key findings")
        st.caption("The first findings in report order. Open Analysis for the full narrative and Sources for the evidence.")
        for number, insight in enumerate(result.insights[:3], start=1):
            insight_card(st, insight, number)


def _context(st, result: PipelineResult) -> None:
    left, middle, right = st.columns(3)
    left.metric("Pages", result.document.page_count)
    middle.metric("Observations", len(result.observations))
    right.metric("Validated analyses", sum(item.result is not None for item in result.analysis_results))
    st.subheader(result.profile.overview_title or result.profile.document_type or "Document overview")
    st.write(result.profile.document_summary or result.profile.document_purpose)
    if result.profile.document_summary_pages:
        st.caption("Summary source pages: " + ", ".join(map(str, result.profile.document_summary_pages)))
    for point in result.profile.overview_points:
        st.markdown(f"- {point}")
    if result.profile.detected_time_periods:
        st.caption("Reporting periods found: " + " · ".join(result.profile.detected_time_periods))
    if result.profile.important_sections:
        st.markdown("**Important sections**")
        st.write(" · ".join(result.profile.important_sections))


def _literal(text: str) -> str:
    """Display source-derived prose as text, without loading Markdown media."""
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>$])", lambda match: "\\" + match.group(0), text)
