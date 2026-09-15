"""Overview result tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    left, middle, right = st.columns(3)
    left.metric("Pages", result.document.page_count)
    middle.metric("Observations", len(result.observations))
    right.metric("Validated analyses", sum(item.result is not None for item in result.analysis_results))
    st.subheader(result.profile.document_type)
    st.write(result.profile.document_purpose)
    if result.profile.important_sections:
        st.write("Important sections:", ", ".join(result.profile.important_sections))
    if result.profile.data_quality_notes:
        for note in result.profile.data_quality_notes:
            st.warning(note)

