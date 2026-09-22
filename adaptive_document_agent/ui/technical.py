"""Developer-level pipeline detail tab."""

import re

from adaptive_document_agent.models import PipelineResult


def _extract_presentation_errors(message: str) -> list[str]:
    """Parse out specific validation failure items from diagnostic messages."""
    cleaned = message
    for prefix in (
        "The AI presentation plan could not be retained. Reason:",
        "Presentation plan validation failed.",
        "Initial reason:",
        "AI repair reason:",
        "Deterministic repair reason:",
    ):
        cleaned = cleaned.replace(prefix, "")

    parts = [p.strip() for p in re.split(r"[;\n]", cleaned) if p.strip()]
    errors: list[str] = []
    seen: set[str] = set()
    for part in parts:
        clean_part = re.sub(
            r"^(?:Invalid presentation plan:\s*|AI repair reason:\s*|Deterministic repair reason:\s*)",
            "",
            part,
        ).strip()
        if (
            clean_part
            and len(clean_part) > 4
            and clean_part.casefold() not in seen
            and not clean_part.startswith("The AI presentation plan")
        ):
            seen.add(clean_part.casefold())
            errors.append(clean_part)
    return errors


def render(st, result: PipelineResult) -> None:
    presentation_failure = next(
        (issue for issue in result.validation_warnings if issue.code == "presentation_plan_failed"),
        None,
    )
    if presentation_failure:
        st.subheader("Presentation Plan Diagnostics")
        st.warning("AI presentation plan validation details:")
        errors = _extract_presentation_errors(presentation_failure.message)
        if errors:
            for error in errors:
                st.markdown(f"- `{error}`")
        else:
            st.markdown(f"- `{presentation_failure.message}`")
        if any(issue.code == "presentation_plan_fallback" for issue in result.validation_warnings):
            st.info("A deterministic evidence-only fallback presentation was generated in place of the invalid AI plan.")
    elif result.presentation_plan:
        st.subheader("Presentation Plan Diagnostics")
        from adaptive_document_agent.services.presentation_editorial import review_presentation
        editorial = review_presentation(result.presentation_plan, result)
        if editorial:
            st.warning("Presentation plan has editorial findings; evidence validation alone does not certify report quality.")
        else:
            st.success("Presentation plan passed the automated evidence and editorial checks.")
        st.caption(f"Planning origin: {result.presentation_plan.planning_origin}")

    st.subheader("Document Profile")
    st.json(result.profile.model_dump(mode="json"))
    st.subheader("Candidate Scores")
    st.json([item.model_dump(mode="json") for item in result.candidate_scores])
    st.subheader("Analysis Plan")
    st.json([item.model_dump(mode="json") for item in result.analysis_plan])
    st.subheader("Executed Tools and Results")
    st.json([item.model_dump(mode="json") for item in result.analysis_results])
    st.subheader("LLM Usage")
    st.json(result.llm_usage)
    st.subheader("Pipeline Timing (ms)")
    st.json(result.timings_ms)
