"""Developer-level pipeline detail tab."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
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

