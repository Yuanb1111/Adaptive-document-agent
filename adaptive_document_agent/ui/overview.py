"""Overview result tab."""

from adaptive_document_agent.models import PipelineResult
from .branding import insight_card


def render(st, result: PipelineResult) -> None:
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
    if result.profile.data_quality_notes:
        notes = list(dict.fromkeys(result.profile.data_quality_notes))
        st.warning(
            f"{len(notes)} data-quality note(s) may affect interpretation. "
            "Open the details below or use the Data Quality tab for the full audit."
        )
        with st.expander("Data-quality notes", expanded=False):
            for note in notes:
                st.markdown(f"- {note}")
    if result.insights:
        st.subheader("Key findings")
        st.caption("The first findings in report order. Open Analysis for the full narrative and Sources for the evidence.")
        for number, insight in enumerate(result.insights[:3], start=1):
            insight_card(st, insight, number)
