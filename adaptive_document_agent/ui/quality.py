"""Data-quality and validation tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    if not result.validation_warnings and not result.profile.data_quality_notes:
        st.success("No validation warnings were produced.")
    for issue in result.validation_warnings:
        method = st.error if issue.severity == "error" else st.warning if issue.severity == "warning" else st.info
        method(f"{issue.stage}: {issue.message}")

