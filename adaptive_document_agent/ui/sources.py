"""Evidence inspection tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    st.caption(f"Evidence for {len(result.insights)} insight(s), grouped in report order.")
    for index, insight in enumerate(result.insights):
        with st.expander(f"{index + 1}. {insight.title}", expanded=False):
            for source in insight.evidence:
                st.write({"page": source.page, "text": source.text, "table_id": source.table_id, "row": source.row_label, "column": source.column_label, "method": source.extraction_method, "confidence": source.confidence})
