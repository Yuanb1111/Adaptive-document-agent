"""Data-quality and validation tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa

    qa = run_comprehensive_qa(result)
    validation_errors = [item for item in result.validation_warnings if item.severity == "error"]
    validation_warnings = [item for item in result.validation_warnings if item.severity == "warning"]
    validation_info = [item for item in result.validation_warnings if item.severity == "info"]
    qa_warnings = qa.warnings
    profile_notes = list(dict.fromkeys(result.profile.data_quality_notes))

    st.caption(
        f"Critical blockers: {len(qa.critical_errors)} · Validation errors: {len(validation_errors)} · "
        f"Warnings: {len(validation_warnings) + len(qa_warnings)} · Profile notes: {len(profile_notes)}"
    )
    if qa.has_critical_errors:
        st.error(f"{len(qa.critical_errors)} critical QA blocker(s) detected. PowerPoint export may be unavailable.")
        with st.expander("Critical blockers", expanded=False):
            for err in qa.critical_errors:
                st.markdown(f"- **[{err.code}]** {err.message}")

    repaired_items = [i for i in qa.info if i.code == "claim_contradiction_repaired"]
    if repaired_items:
        st.info(f"Automatic QA repaired {len(repaired_items)} contradictory claim(s).")
        with st.expander("Automatic repair details", expanded=False):
            for item in repaired_items:
                st.markdown(f"- {item.message}")

    if not result.validation_warnings and not profile_notes and not qa.has_critical_errors:
        st.success("No validation warnings were produced.")
    elif validation_errors or validation_warnings or qa_warnings:
        st.warning(
            f"{len(validation_errors) + len(validation_warnings) + len(qa_warnings)} issue(s) need review. "
            "They are grouped below instead of shown as separate alert cards."
        )

    groups = (
        ("Validation errors", validation_errors),
        ("Validation warnings", validation_warnings),
        ("Presentation QA warnings", qa_warnings),
        ("Informational checks", validation_info),
    )
    for title, items in groups:
        if items:
            with st.expander(f"{title} ({len(items)})", expanded=False):
                for issue in items:
                    stage = getattr(issue, "stage", "presentation")
                    st.markdown(f"- **{stage} · {issue.code}** — {issue.message}")
    if profile_notes:
        with st.expander(f"Document limitations ({len(profile_notes)})", expanded=False):
            for note in profile_notes:
                st.markdown(f"- {note}")
