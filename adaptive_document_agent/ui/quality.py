"""Data-quality and validation tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa

    qa = run_comprehensive_qa(result)
    if qa.has_critical_errors:
        st.error(f"🔴 **QA Audit: {len(qa.critical_errors)} Critical Blocker(s) Detected**")
        for err in qa.critical_errors:
            st.error(f"• **[{err.code}]** {err.message}")

    repaired_items = [i for i in qa.info if i.code == "claim_contradiction_repaired"]
    if repaired_items:
        st.info(f"ℹ️ **Automatic QA Repair: {len(repaired_items)} Contradictory Claim(s) Resolved**")
        with st.expander("View Repaired Slide Claims", expanded=False):
            for item in repaired_items:
                st.markdown(f"- {item.message}")

    if not result.validation_warnings and not result.profile.data_quality_notes and not qa.has_critical_errors:
        st.success("No validation warnings were produced.")
    for issue in result.validation_warnings:
        method = st.error if issue.severity == "error" else st.warning if issue.severity == "warning" else st.info
        method(f"{issue.stage}: {issue.message}")


