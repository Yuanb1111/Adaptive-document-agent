"""Evidence inspection tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    st.caption(f"Evidence for {len(result.insights)} insight(s), grouped in report order.")
    if not result.insights:
        st.info("No insight-level evidence is available. Extracted Data may still contain source observations.")
    for index, insight in enumerate(result.insights):
        with st.expander(f"{index + 1}. {insight.title}", expanded=False):
            if not insight.evidence:
                st.info("No page evidence is attached to this insight.")
            for source in insight.evidence:
                st.markdown(f"**Page {source.page}**")
                # Native text keeps document content inert and preserves raw wording.
                if source.text:
                    st.text(source.text)
                else:
                    st.caption("No source text was retained for this evidence item.")
                details = {"Table": source.table_id, "Row": source.row_label,
                           "Column": source.column_label, "Method": source.extraction_method,
                           "Confidence": source.confidence}
                st.caption(" · ".join(f"{key}: {value}" for key, value in details.items() if value is not None))
                st.divider()
