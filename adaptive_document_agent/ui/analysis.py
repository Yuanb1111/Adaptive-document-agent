"""Analysis report tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    st.markdown(result.report_markdown)

