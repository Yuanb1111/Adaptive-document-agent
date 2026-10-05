"""Professional Streamlit shell over the stable orchestration API."""

import logging
from threading import Lock
from uuid import uuid4

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.routing import create_llm_client
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION, ANALYSIS_VERSION, EXTRACTION_VERSION

from . import analysis, branding, data, deliverables, overview, quality, sources, technical
from .charts import chart_rows, render_chart
from .deployment import cache_for_session, is_public_deployment
from .sidebar import render_sidebar

_LOGGER = logging.getLogger("adaptive_document_agent.timing.analysis_attempt")
_ATTEMPT_LOCK = Lock()


def _analysis_scope_key(raw_pdf: bytes, analysis_focus: str, settings) -> str:
    """Invalidate finished outputs independently of reusable model/extraction caches."""
    return sha256_bytes(
        "|".join(
            (
                PIPELINE_VERSION,
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
                str(settings.discovery_thinking),
                str(settings.simple_task_reasoning),
                str(settings.discovery_chunk_tokens),
                str(settings.semantic_batch_size),
                str(settings.deepseek_price_band),
            )
        ).encode("utf-8")
    )


def _analysis_failure(st, scope_key):
    attempt = st.session_state.get("analysis_attempts", {}).get(scope_key)
    if attempt and attempt["state"] in {"failed", "interrupted"}:
        return attempt["failure"]
    failure = st.session_state.get("analysis_failure")
    return failure if failure and failure["scope_key"] == scope_key else None


def _render_analysis_failure(st, failure, progress=None):
    if progress:
        progress.fail("Analysis could not be completed")
    st.error(failure["message"])
    if failure["usage"]:
        from .llm_costs import render as render_costs
        render_costs(st, failure["usage"])


def _retry_analysis_button(st, scope_key):
    return st.button("Retry analysis (reuse successful cache)", key=f"retry_analysis_{scope_key}")


def _render_active_attempt(st, attempt, progress):
    if progress:
        progress.update(attempt["stage"])
    st.info("This analysis is still running. Wait for it to finish before retrying.")


def _analyse_upload(st, raw_pdf, *, scope_key, analysis_focus, settings, cache, scope=None, force=False, retry=False, progress=None):
    """Run one upload through discovery and analysis, reusing it on widget reruns."""
    with _ATTEMPT_LOCK:
        attempts = st.session_state.setdefault("analysis_attempts", {})
        active = attempts.get(scope_key)
        active = active if active and active["state"] == "running" else None
    if active:
        _render_active_attempt(st, active, progress)
        return None
    failure = _analysis_failure(st, scope_key)
    if failure and not (force or retry):
        _render_analysis_failure(st, failure, progress)
        return None
    # An explicit retry starts a new attempt, retaining successful model caches
    # rather than returning an older complete result from before the failure.
    if not (force or retry) and st.session_state.get("analysis_result_key") == scope_key:
        cached = st.session_state.get("analysis_result")
        if cached is not None:
            st.session_state["analysis_result_reused"] = True
            if progress:
                progress.update("Complete")
            return cached
    if not (force or retry) and cache is not None:
        from adaptive_document_agent.models import PipelineResult
        cached = cache.get_model(f"analysis-result-{scope_key}", PipelineResult)
        if cached is not None:
            st.session_state["analysis_result_reused"] = True
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
    # Streamlit may overlap script runners during a rerun. Claim the attempt
    # after cache lookup, before the first UI write that can interrupt it.
    with _ATTEMPT_LOCK:
        previous = attempts.get(scope_key)
        active = previous if previous and previous["state"] == "running" else None
        # Another runner can finish or be interrupted during our cache lookup.
        failure = (previous["failure"] if previous and previous["state"] in {"failed", "interrupted"}
                   and not (force or retry) else None)
        completed = (st.session_state.get("analysis_result")
                     if not (force or retry) and st.session_state.get("analysis_result_key") == scope_key
                     else None)
        if active is None and failure is None and completed is None:
            attempt = {"id": uuid4().hex, "state": "running", "stage": "Starting analysis"}
            attempts[scope_key] = attempt
    if active:
        _render_active_attempt(st, active, progress)
        return None
    if failure:
        _render_analysis_failure(st, failure, progress)
        return None
    if completed is not None:
        st.session_state["analysis_result_reused"] = True
        if progress:
            progress.update("Complete")
        return completed
    status = None
    gateway = None
    try:
        _LOGGER.info("Analysis attempt %s started", attempt["id"])
        if progress:
            progress.reset()
        gateway = LLMGateway(create_llm_client(settings), settings, cache_enabled=not force)
        pending_scope = st.session_state.get("analysis_scope_usage_pending")
        if scope is not None and pending_scope and pending_scope["key"] == scope_key:
            gateway.usage.extend(pending_scope["records"])
            del st.session_state["analysis_scope_usage_pending"]
        status = st.status("Analysing PDF and preparing presentation…", expanded=True)

        def update(stage: str) -> None:
            attempt["stage"] = stage
            _LOGGER.info("Analysis attempt %s stage: %s", attempt["id"], stage)
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
        st.session_state["analysis_result_reused"] = False
        st.session_state["analysis_result_key"] = scope_key
        if cache is not None:
            cache.set_model(f"analysis-result-{scope_key}", result)
        if _analysis_failure(st, scope_key):
            del st.session_state["analysis_failure"]
        attempt["state"] = "complete"
        _LOGGER.info("Analysis attempt %s completed", attempt["id"])
        status.update(label="Analysis complete", state="complete", expanded=False)
        return result
    except Exception as exc:
        usage = list(getattr(gateway, "usage", []))
        # Replace this attempt's ledger; widget reruns only display it and must
        # never add its paid requests to another attempt's costs.
        failure = {"scope_key": scope_key, "scope": scope,
                   "message": f"Analysis could not be completed: {exc}", "usage": usage}
        # Save the failure before UI updates, which can themselves be interrupted.
        attempt.update(state="failed", failure=failure)
        st.session_state["failed_llm_usage"] = usage
        st.session_state["analysis_failure"] = failure
        _LOGGER.info("Analysis attempt %s failed at %s", attempt["id"], attempt["stage"])
        if status is not None:
            status.update(label="Analysis failed", state="error", expanded=True)
        _render_analysis_failure(st, failure, progress)
        return None
    except BaseException:
        # Streamlit stop/rerun exceptions must propagate. Mutate the already
        # stored record directly: session_state writes can trigger another stop.
        if attempt["state"] == "running":
            attempt.update(state="interrupted", failure={
                "scope_key": scope_key, "scope": scope,
                "message": "Analysis was interrupted. Retry to reuse successful cached work.",
                "usage": list(getattr(gateway, "usage", [])),
            })
            _LOGGER.info("Analysis attempt %s interrupted at %s", attempt["id"], attempt["stage"])
        raise


def run_app() -> None:
    from adaptive_document_agent.utils.timing import configure_timing_logging
    configure_timing_logging()
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Streamlit is not installed. Install requirements.txt.") from exc

    st.set_page_config(page_title="FOURIER | Document Intelligence", page_icon="📄", layout="wide")
    branding.apply_theme(st)
    branding.header(st)
    public_deployment = is_public_deployment()
    settings = render_sidebar(st, public_deployment=public_deployment)
    from adaptive_document_agent.services.export_readiness import check_export_readiness
    readiness = check_export_readiness(st.session_state.setdefault("ppt_readiness_cache", {}))
    with st.sidebar:
        with st.expander("Application status", expanded=False):
            st.caption(f"Running pipeline: {PIPELINE_VERSION}")
            if public_deployment:
                if st.get_option("server.fileWatcherType") == "none":
                    st.caption("Source reload: disabled (restart required for code updates)")
                else:
                    st.warning(
                        "Source reload is enabled. For stable production imports, set "
                        "server.fileWatcherType to 'none' and reboot the app."
                    )
            if readiness["ready"]:
                st.caption(f"PowerPoint export environment ready: {readiness['backend']}")
            else:
                st.caption(readiness["message"])
    if not readiness["ready"]:
        st.warning("PowerPoint export is currently unavailable. Analysis and other download formats remain available.")
    cache = cache_for_session(st.session_state, public_deployment=public_deployment)
    with st.container(border=True):
        branding.section_label(st, "01", "Upload your document")
        with st.expander("Analysis options (optional)", expanded=False):
            analysis_focus = st.text_area(
                "Analysis focus (optional)",
                placeholder="e.g. Compare performance and highlight disclosed risks.",
                height=88,
                help="Leave blank for automatic discovery. Changing the focus or model after upload starts a new analysis.",
            )
            review_scope = st.toggle(
                "Review page scope before analysis (optional)", value=False,
                help="Review and confirm selected page ranges before deep analysis begins.",
            )
        uploaded = st.file_uploader("Upload one PDF", type=["pdf"], accept_multiple_files=False)
        st.caption("Analysis starts automatically after upload unless page-scope review is enabled.")
    if not uploaded:
        return
    raw_pdf = uploaded.getvalue()
    scope_key = _analysis_scope_key(raw_pdf, analysis_focus, settings)
    result = st.session_state.get("analysis_result") if st.session_state.get("analysis_result_key") == scope_key else None
    from .processing_progress import ProcessingProgress
    progress = ProcessingProgress(st.empty())
    if result is not None:
        progress.update("Complete")
    failure = _analysis_failure(st, scope_key)
    retry_button_shown = failure is not None
    retry_requested = _retry_analysis_button(st, scope_key) if retry_button_shown else False
    analysis_attempted = False
    if retry_requested:
        analysis_attempted = True
        result = _analyse_upload(
            st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
            settings=settings, cache=cache, scope=failure["scope"], retry=True,
            progress=progress,
        )
    elif review_scope:
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
                pending = st.session_state.get("analysis_scope_usage_pending", {})
                previous = pending.get("records", []) if pending.get("key") == scope_key else []
                st.session_state["analysis_scope_usage_pending"] = {
                    "key": scope_key, "records": [*previous, *gateway.usage],
                }
                status.update(label="Analysis scope ready", state="complete", expanded=False)
            except Exception as exc:
                progress.fail("Analysis scope could not be prepared")
                st.error(f"Analysis scope could not be prepared: {exc}")
                usage = list(gateway.usage) if "gateway" in locals() else []
                if usage:
                    st.session_state["failed_llm_usage"] = usage
                    from .llm_costs import render as render_costs
                    render_costs(st, usage)
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
                analysis_attempted = True
                result = _analyse_upload(
                    st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
                    settings=settings, cache=cache, scope=preview, force=True,
                    progress=progress,
                )
        elif result is None:
            st.info("Review and confirm the page scope before starting deep analysis, or turn off this optional review to run automatically.")
    else:
        analysis_attempted = True
        result = _analyse_upload(
            st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
            settings=settings, cache=cache,
            progress=progress,
        )
    if not analysis_attempted and failure:
        _render_analysis_failure(st, failure, progress)
        result = None
    if result is None:
        if _analysis_failure(st, scope_key) and not retry_button_shown:
            _retry_analysis_button(st, scope_key)
        return
    branding.result_heading(st, result)
    with st.expander("Rerun analysis or rebuild presentation", expanded=False):
        st.caption("Reanalysis makes new model requests. Rebuilding PowerPoint reuses the existing analysis.")
        if st.button("Reanalyse PDF (ignore model cache)"):
            result = _analyse_upload(
                st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
                settings=settings, cache=cache, force=True, progress=progress,
                scope=st.session_state.get("analysis_scope") if review_scope else None,
            )
            if result is None:
                if not retry_button_shown:
                    _retry_analysis_button(st, scope_key)
                return
        if st.button("Regenerate PowerPoint only"):
            st.session_state["ppt_build_cache"] = {}
            st.session_state["ppt_visual_cache"] = {}
            st.caption("Reusing the existing analysis; rebuilding PowerPoint and rerunning export checks.")

    deliverables.render(st, result, raw_pdf, progress)
    st.divider()
    branding.section_label(st, "03", "Explore the evidence")
    st.caption("Read the findings, inspect the exact chart data, and trace each conclusion back to its source.")
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
        if st.session_state.get("analysis_result_reused"):
            st.caption("Reused analysis result: the ledger below records its original generation, not new model charges for this view.")
        technical.render(st, result)
