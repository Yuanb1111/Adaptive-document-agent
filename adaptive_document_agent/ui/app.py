"""Professional Streamlit shell over the stable orchestration API."""

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.routing import create_llm_client
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION, ANALYSIS_VERSION, EXTRACTION_VERSION

from . import analysis, data, deliverables, overview, quality, sources, technical
from .charts import chart_rows, render_chart
from .deployment import cache_for_session, is_public_deployment
from .sidebar import render_sidebar


def _analyse_upload(st, raw_pdf, *, scope_key, analysis_focus, settings, cache, scope=None, force=False, progress=None):
    """Run one upload through discovery and analysis, reusing it on widget reruns."""
    if not force and st.session_state.get("analysis_result_key") == scope_key:
        cached = st.session_state.get("analysis_result")
        if cached is not None:
            if progress:
                progress.update("Complete")
            return cached
    if not force and cache is not None:
        from adaptive_document_agent.models import PipelineResult
        cached = cache.get_model(f"analysis-result-{scope_key}", PipelineResult)
        if cached is not None:
            st.session_state["analysis_result"] = cached
            st.session_state["analysis_result_key"] = scope_key
            if progress:
                progress.update("Complete")
            return cached
    if not settings.model:
        if progress:
            progress.fail("Configure a model before analysis")
        st.error("Configure a model before analysis.")
        return None
    if progress:
        progress.reset()
    status = None
    try:
        gateway = LLMGateway(create_llm_client(settings), settings, cache_enabled=not force)
        status = st.status("Analysing PDF and preparing presentation…", expanded=True)

        def update(stage: str) -> None:
            status.write(stage)
            if progress:
                progress.update(stage)

        result = DocumentOrchestrator(gateway, cache=cache).analyse_pdf(
            raw_pdf,
            progress=update,
            analysis_focus=analysis_focus,
            scope=scope,
        )
        st.session_state["analysis_result"] = result
        st.session_state["analysis_result_key"] = scope_key
        if cache is not None:
            cache.set_model(f"analysis-result-{scope_key}", result)
        status.update(label="Analysis complete", state="complete", expanded=False)
        return result
    except Exception as exc:
        if status is not None:
            status.update(label="Analysis failed", state="error", expanded=True)
        if progress:
            progress.fail("Analysis could not be completed")
        st.error(f"Analysis could not be completed: {exc}")
        return None


def run_app() -> None:
    from adaptive_document_agent.utils.timing import configure_timing_logging
    configure_timing_logging()
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Streamlit is not installed. Install requirements.txt.") from exc

    st.set_page_config(page_title="Adaptive Document Intelligence Agent", page_icon="📄", layout="wide")
    st.title("Adaptive Document Intelligence Agent")
    st.caption(f"Running pipeline: {PIPELINE_VERSION}")
    st.markdown(
        "Upload a PDF and the Agent will understand the document, discover useful data, "
        "run deterministic calculations, validate results, and preserve page-level evidence."
    )
    public_deployment = is_public_deployment()
    if public_deployment:
        if st.get_option("server.fileWatcherType") == "none":
            st.caption("Source reload: disabled (restart required for code updates)")
        else:
            st.warning(
                "Source reload is enabled. For stable production imports, set "
                "server.fileWatcherType to 'none' and reboot the app."
            )
    settings = render_sidebar(st, public_deployment=public_deployment)
    from adaptive_document_agent.services.export_readiness import check_export_readiness
    readiness = check_export_readiness(st.session_state.setdefault("ppt_readiness_cache", {}))
    if readiness["ready"]:
        st.caption(f"PowerPoint export environment ready: {readiness['backend']}")
    else:
        st.warning("PowerPoint export environment is not ready. " + readiness["message"])
        st.caption("Analysis and other formats remain available. Fix the renderer before expecting a verified PowerPoint download.")
    cache = cache_for_session(st.session_state, public_deployment=public_deployment)
    analysis_focus = st.text_area(
        "Analysis focus (optional)",
        placeholder="Describe what you want the Agent to find and analyse. Leave blank for automatic discovery.",
        height=90,
    )
    review_scope = st.toggle("Review page scope before analysis (optional)", value=False)
    uploaded = st.file_uploader("Upload one PDF", type=["pdf"], accept_multiple_files=False)
    if not uploaded:
        st.info("Upload a PDF to begin. You do not need to choose a document type.")
        return
    raw_pdf = uploaded.getvalue()
    scope_key = sha256_bytes(
        "|".join(
            (
                ANALYSIS_VERSION,
                EXTRACTION_VERSION,
                sha256_bytes(raw_pdf),
                analysis_focus.strip(),
                settings.provider.value,
                settings.model,
                settings.base_url or "",
                settings.privacy_mode.value,
                str(sorted(settings.stage_models.items())),
                str(settings.temperature),
            )
        ).encode("utf-8")
    )
    result = st.session_state.get("analysis_result") if st.session_state.get("analysis_result_key") == scope_key else None
    from .processing_progress import ProcessingProgress
    progress = ProcessingProgress(st.empty())
    if result is not None:
        progress.update("Complete")
    if review_scope:
        if st.button("Review analysis scope"):
            if not settings.model:
                st.error("Configure a model before analysis.")
                return
            try:
                gateway = LLMGateway(create_llm_client(settings), settings)
                status = st.status("Preparing analysis scope…", expanded=True)

                def update(stage: str) -> None:
                    status.write(stage)
                    progress.update(stage)

                preview = DocumentOrchestrator(gateway, cache=cache).preview_scope(
                    raw_pdf,
                    progress=update,
                    analysis_focus=analysis_focus,
                )
                st.session_state["analysis_scope"] = preview
                st.session_state["analysis_scope_key"] = scope_key
                status.update(label="Analysis scope ready", state="complete", expanded=False)
            except Exception as exc:
                progress.fail("Analysis scope could not be prepared")
                st.error(f"Analysis scope could not be prepared: {exc}")
                return
        preview = st.session_state.get("analysis_scope") if st.session_state.get("analysis_scope_key") == scope_key else None
        if preview:
            st.subheader("Confirm analysis scope")
            st.dataframe(
                [
                    {
                        "Section": item.title,
                        "Start page": item.start_page,
                        "End page": item.end_page,
                        "Pages": item.end_page - item.start_page + 1,
                        "Why selected": item.reason,
                    }
                    for item in preview.page_ranges
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"Selected {preview.selected_page_count} of {preview.page_count} pages. Confirm to replace the automatic analysis with these ranges.")
            confirmed = st.checkbox("I confirm these page ranges for deep analysis", key=f"confirm_{scope_key}")
            if st.button("Analyse selected pages", type="primary", disabled=not confirmed):
                updated = _analyse_upload(
                    st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
                    settings=settings, cache=cache, scope=preview, force=True,
                    progress=progress,
                )
                if updated is None:
                    return
                result = updated
        elif result is None:
            st.info("Review and confirm the page scope before starting deep analysis, or turn off this optional review to run automatically.")
    else:
        result = _analyse_upload(
            st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
            settings=settings, cache=cache,
            progress=progress,
        )
    if result is None:
        return
    if st.button("Reanalyse PDF (ignore model cache)"):
        result = _analyse_upload(
            st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
            settings=settings, cache=cache, force=True, progress=progress,
            scope=st.session_state.get("analysis_scope") if review_scope else None,
        )
        if result is None:
            return
    if st.button("Regenerate PowerPoint only"):
        st.session_state["ppt_build_cache"] = {}
        st.session_state["ppt_visual_cache"] = {}
        st.caption("Reusing the existing analysis; rebuilding PowerPoint and rerunning export checks.")

    deliverables.render(st, result, raw_pdf, progress)
    st.divider()
    st.subheader("Explore the analysis")
    tab_overview, tab_analysis, tab_charts, tab_data, tab_sources, tab_quality, tab_technical = st.tabs(["Overview", "Analysis", "Charts", "Extracted Data", "Sources", "Data Quality", "Technical Details"])
    with tab_overview:
        overview.render(st, result)
    with tab_analysis:
        analysis.render(st, result)
    with tab_charts:
        index = DocumentIndex(result.observations)
        if not result.charts:
            st.info("No chart met the usefulness and evidence thresholds.")
        if result.charts:
            st.caption(f"{len(result.charts)} validated visual(s), shown in analytical order.")
        for chart_index, plan in enumerate(result.charts):
            with st.expander(f"{chart_index + 1}. {plan.title}", expanded=chart_index == 0):
                style_labels = {
                    "line": "Line",
                    "bar": "Vertical bar",
                    "horizontal_bar": "Horizontal bar",
                    "area": "Area",
                    "pie": "Pie",
                    "scatter": "Scatter",
                    "table": "Data table",
                }
                available = plan.available_chart_types or [plan.chart_type]
                selected_style = st.selectbox(
                    f"Chart style — {plan.title}",
                    available,
                    format_func=lambda value: style_labels.get(value, value),
                    key=f"chart_style_{plan.id}",
                )
                show_labels = st.toggle("Show values directly on chart", value=True, key=f"chart_labels_{plan.id}")
                st.plotly_chart(
                    render_chart(plan, index, chart_type=selected_style, show_data_labels=show_labels),
                    use_container_width=True,
                )
                st.caption(f"Source pages: {', '.join(map(str, plan.source_pages))}")
                with st.expander("View the exact data used in this visual"):
                    st.dataframe(chart_rows(plan, index), use_container_width=True, hide_index=True)
    with tab_data:
        data.render(st, result)
    with tab_sources:
        sources.render(st, result)
    with tab_quality:
        quality.render(st, result)
    with tab_technical:
        technical.render(st, result)
