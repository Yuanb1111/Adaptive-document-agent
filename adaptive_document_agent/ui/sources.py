"""Evidence inspection tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    for insight in result.insights:
        with st.expander(insight.title):
            for source in insight.evidence:
                st.write({"page": source.page, "text": source.text, "table_id": source.table_id, "row": source.row_label, "column": source.column_label, "method": source.extraction_method, "confidence": source.confidence})

