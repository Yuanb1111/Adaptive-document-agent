"""Developer-level pipeline detail tab."""

from contextlib import nullcontext
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


def _expander(st, label: str):
    """Return a collapsed expander while tolerating lightweight UI test doubles."""
    try:
        container = st.expander(label, expanded=False)
    except TypeError:
        container = st.expander(label)
    return container if hasattr(container, "__enter__") else nullcontext()


def render(st, result: PipelineResult) -> None:
    st.caption(f"Result pipeline version: {result.pipeline_version or 'unknown (older export)'}")
    st.caption(
        f"Candidates: {len(result.candidate_scores)} · Planned analyses: {len(result.analysis_plan)} · "
        f"Executed results: {len(result.analysis_results)} · Model calls: {len(result.llm_usage)}"
    )
    presentation_failure = next(
        (issue for issue in result.validation_warnings if issue.code == "presentation_plan_failed"),
        None,
    )
    if presentation_failure:
        st.warning("AI presentation plan validation details:")
        errors = _extract_presentation_errors(presentation_failure.message)
        with _expander(st, "Presentation plan diagnostics"):
            if errors:
                for error in errors:
                    st.markdown(f"- `{error}`")
            else:
                st.markdown(f"- `{presentation_failure.message}`")
        if any(issue.code == "presentation_plan_fallback" for issue in result.validation_warnings):
            st.info(
                "A validated question-first or evidence-only fallback presentation "
                "replaced the invalid AI slide draft."
            )
    elif result.presentation_plan:
        from adaptive_document_agent.services.presentation_editorial import review_presentation
        editorial = review_presentation(result.presentation_plan, result)
        if editorial:
            st.warning(
                "Presentation plan has editorial findings; evidence validation alone "
                "does not certify report quality."
            )
        else:
            st.success("Presentation plan passed the automated evidence and editorial checks.")
        st.caption(f"Planning origin: {result.presentation_plan.planning_origin}")

    for issue in result.validation_warnings:
        if issue.code == "presentation_plan_fallback_failed":
            st.error(issue.message)
    if result.presentation_plan is None:
        st.warning("No validated presentation plan is available. PowerPoint uses the legacy draft layout.")

    if result.presentation_topics:
        with _expander(st, "Presentation questions selected before charts"):
            st.json([item.model_dump(mode="json") for item in result.presentation_topics.topics])
            if result.presentation_topics.omissions:
                st.caption("Important evidence considered but not promoted to a presentation topic")
                st.json([item.model_dump(mode="json") for item in result.presentation_topics.omissions])

    sections = (
        ("Document profile", result.profile.model_dump(mode="json")),
        ("Candidate scores", [item.model_dump(mode="json") for item in result.candidate_scores]),
        ("Analysis plan", [item.model_dump(mode="json") for item in result.analysis_plan]),
        ("Executed tools and results", [item.model_dump(mode="json") for item in result.analysis_results]),
        ("LLM usage", result.llm_usage),
        ("Pipeline timing (ms)", result.timings_ms),
    )
    for title, payload in sections:
        with _expander(st, title):
            st.json(payload)
