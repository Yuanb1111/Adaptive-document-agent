"""Professional Streamlit shell over the stable orchestration API."""

import logging
from threading import Lock

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.routing import create_llm_client
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION, ANALYSIS_VERSION, EXTRACTION_VERSION

from . import analysis, branding, data, deliverables, overview, quality, sources, technical
from .deployment import cache_for_session, is_public_deployment
from .sidebar import render_sidebar
from .analysis_job import execute as execute_analysis, new_attempt, snapshot as attempt_snapshot
from .analysis_job import start_worker as _start_analysis_worker
from adaptive_document_agent.services.pipeline_completion import is_complete

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
    if attempt and attempt["state"] in {"failed", "interrupted", "partial"}:
        return attempt["failure"]
    failure = st.session_state.get("analysis_failure")
    return failure if failure and failure["scope_key"] == scope_key else None


def _render_analysis_failure(st, failure, progress=None):
    from .completion_notification import notify_outcome
    attempt = st.session_state.get('analysis_attempts', {}).get(failure['scope_key'], {})
    notify_outcome(st, 'analysis_interrupted' if attempt.get('state') == 'interrupted'
                   else 'analysis_failed', scope_key=failure['scope_key'])
    if progress:
        if 'progress' in attempt:
            progress.restore(attempt_snapshot(attempt)['progress'])
        else:
            progress.fail("Analysis could not be completed")
    st.error(failure["message"])
    if failure.get('diagnostics'):
        import json
        st.download_button('Download failure diagnostics (.json)',
            json.dumps(failure['diagnostics'], ensure_ascii=False, indent=2),
            'analysis_failure_diagnostics.json', 'application/json',
            key='download_analysis_failure_diagnostics', on_click='ignore',
            help='Includes model responses derived from your document. Share only with intended recipients.')
    if failure["usage"]:
        from .llm_costs import render as render_costs
        render_costs(st, failure["usage"])


def _retry_analysis_button(st, scope_key):
    active=st.session_state.get('analysis_attempts',{}).get(scope_key,{})
    return st.button("Retry analysis (reuse successful cache)", key=f"retry_analysis_{scope_key}",
                     disabled=active.get('state')=='running')


def _poll_active_attempt(st, attempt, progress):
    current = attempt_snapshot(attempt)
    if current['state'] != 'running':
        # Leave the fragment and publish the result/error through the full app.
        st.rerun()
        return
    if progress:
        progress.mount(st)
        progress.restore(current['progress'])


def _render_active_attempt(st, attempt, progress):
    if progress:
        progress.clear()
    st.fragment(run_every=1)(_poll_active_attempt)(st, attempt, progress)


def _publish_attempt(st, attempt, scope_key, cache, progress):
    """Only the UI thread writes session state or the finished-result cache."""
    current = attempt_snapshot(attempt)
    result = current.get('result')
    if not current['published']:
        if result is not None:
            st.session_state.update(analysis_result=result, analysis_result_key=scope_key,
                                    analysis_result_reused=False)
        failure = current.get('failure')
        if failure:
            st.session_state['analysis_failure'] = failure
            st.session_state['failed_llm_usage'] = failure['usage']
            if current['state'] == 'partial':
                st.session_state.update(analysis_partial=result, analysis_partial_key=scope_key)
        else:
            if cache is not None:
                cache.set_model(f'analysis-result-{scope_key}', result)
            st.session_state.pop('analysis_failure', None)
            st.session_state.pop('analysis_partial', None)
            st.session_state.pop('analysis_partial_key', None)
        attempt['published'] = True
    if progress:
        progress.restore(current['progress'])
    if current.get('failure'):
        _render_analysis_failure(st, current['failure'], progress)
    return result


def _analyse_upload(st, raw_pdf, *, scope_key, analysis_focus, settings, cache, scope=None, force=False, retry=False,
                    progress=None, presentation_budget=None):
    """Start one worker per attempt, observing it safely across widget reruns."""
    with _ATTEMPT_LOCK:
        attempts = st.session_state.setdefault("analysis_attempts", {})
        previous = attempts.get(scope_key)
        active = previous if previous and previous["state"] == "running" else None
    if active:
        _render_active_attempt(st, active, progress)
        return None
    if previous and not previous.get('published', True):
        result = _publish_attempt(st, previous, scope_key, cache, progress)
        if not (force or retry):
            return result
    failure = _analysis_failure(st, scope_key)
    if failure and not (force or retry):
        _render_analysis_failure(st, failure, progress)
        return st.session_state.get('analysis_partial') if st.session_state.get('analysis_partial_key') == scope_key else None
    # An explicit retry starts a new attempt, retaining successful model caches
    # rather than returning an older complete result from before the failure.
    if not (force or retry) and st.session_state.get("analysis_result_key") == scope_key:
        cached = st.session_state.get("analysis_result")
        if cached is not None and is_complete(cached):
            st.session_state["analysis_result_reused"] = True
            if progress:
                progress.update("Complete")
            return cached
    if not (force or retry) and cache is not None:
        from adaptive_document_agent.models import PipelineResult
        cached = cache.get_model(f"analysis-result-{scope_key}", PipelineResult)
        if cached is not None and is_complete(cached):
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
    pending_scope = st.session_state.get("analysis_scope_usage_pending")
    scope_usage = (list(pending_scope["records"]) if scope is not None and pending_scope
                   and pending_scope["key"] == scope_key else [])
    resume = (st.session_state.get('analysis_partial')
              if retry and not force and st.session_state.get('analysis_partial_key') == scope_key else None)
    if resume is not None and (resume.pipeline_version != PIPELINE_VERSION
                              or any(p.table_extraction_status == 'failed' for p in resume.document.pages)):
        resume = None
    worker_settings = settings.model_copy(deep=True)
    # Streamlit may overlap script runners during a rerun. Claim the attempt
    # after cache lookup, before the first UI write that can interrupt it.
    with _ATTEMPT_LOCK:
        previous = attempts.get(scope_key)
        active = previous if previous and previous["state"] == "running" else None
        pending = previous if previous and not previous.get('published', True) else None
        # Another runner can finish or be interrupted during our cache lookup.
        failure = (previous["failure"] if previous and previous["state"] in {"failed", "interrupted"}
                   and not (force or retry) else None)
        completed = (st.session_state.get("analysis_result")
                     if not (force or retry) and st.session_state.get("analysis_result_key") == scope_key
                     else None)
        if completed is not None and not is_complete(completed):
            completed = None
        if active is None and pending is None and failure is None and completed is None:
            attempt = new_attempt()
            attempts[scope_key] = attempt
    if active:
        _render_active_attempt(st, active, progress)
        return None
    if pending:
        return _publish_attempt(st, pending, scope_key, cache, progress)
    if failure:
        _render_analysis_failure(st, failure, progress)
        return None
    if completed is not None:
        st.session_state["analysis_result_reused"] = True
        if progress:
            progress.update("Complete")
        return completed
    # The worker owns a settings snapshot. Later widget edits cannot alter its
    # provider, credentials, privacy policy or per-stage routing mid-analysis.
    def work():
        execute_analysis(
            attempt, gateway_factory=lambda: LLMGateway(create_llm_client(worker_settings), worker_settings,
                                                        cache_enabled=not force),
            orchestrator_factory=DocumentOrchestrator, raw_pdf=raw_pdf, scope_key=scope_key,
            scope=scope, analysis_focus=analysis_focus, cache=cache, resume=resume,
            presentation_budget=presentation_budget, scope_usage=scope_usage)
    try:
        _start_analysis_worker(work)
    except Exception as exc:
        # A thread-start failure must not leave a permanently "running" record.
        with attempt['lock']:
            attempt['failure'] = {'scope_key': scope_key, 'scope': scope,
                                  'message': f'Analysis could not start: {type(exc).__name__}',
                                  'usage': scope_usage}
            attempt['progress'].fail('Analysis could not start')
            attempt['state'] = 'failed'
    if scope_usage:
        st.session_state.pop('analysis_scope_usage_pending', None)
    if attempt_snapshot(attempt)['state'] != 'running':
        return _publish_attempt(st, attempt, scope_key, cache, progress)
    _render_active_attempt(st, attempt, progress)
    return None


def run_app() -> None:
    from adaptive_document_agent.utils.timing import configure_timing_logging
    configure_timing_logging()
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Streamlit is not installed. Install requirements.txt.") from exc

    st.set_page_config(page_title="FOURIER | Document Intelligence", page_icon="📄", layout="wide")
    branding.apply_theme(st)
    from .completion_notification import render_settings as render_notification_settings
    render_notification_settings(st)
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
                "Analysis and PPT requirements (optional)",
                placeholder="e.g. Focus on profitability, explain the business in detail, and append every table from a named chapter.",
                height=88,
                max_chars=6000,
                help="Specify analysis priorities, content detail, narrative language, or a chapter whose tables belong in Data Index. The result shows interpreted requirements and completion checks. Original source-table cells, names, units and periods remain literal. Changing requirements or model after upload starts a new analysis.",
            )
            review_scope = st.toggle(
                "Review page scope before analysis (optional)", value=False,
                help="Review and confirm selected page ranges before deep analysis begins.",
            )
        uploaded = st.file_uploader("Upload one PDF", type=["pdf"], accept_multiple_files=False)
        st.caption("Analysis starts automatically after upload unless page-scope review is enabled.")
        st.caption('Each analysis has a 15-minute limit. After that, no new model requests or retries '
                   'start; completed evidence is retained. In-flight requests may still be billed.')
    from adaptive_document_agent.services.presentation_requirements import budget_request, fixed_presentation_budget
    presentation_budget = fixed_presentation_budget()
    scope_instructions = budget_request(analysis_focus, presentation_budget)
    if not uploaded:
        return
    raw_pdf = uploaded.getvalue()
    scope_key = _analysis_scope_key(raw_pdf, scope_instructions, settings)
    result = st.session_state.get("analysis_result") if st.session_state.get("analysis_result_key") == scope_key else None
    from .processing_progress import ProcessingProgress
    progress = ProcessingProgress(st.empty(), timer=st.empty())
    if result is not None:
        progress.update("Complete")
    failure = _analysis_failure(st, scope_key)
    retry_button_shown = failure is not None
    retry_requested = _retry_analysis_button(st, scope_key) if retry_button_shown else False
    analysis_attempted = False
    current_attempt = st.session_state.get('analysis_attempts', {}).get(scope_key)
    if current_attempt and (current_attempt['state'] == 'running' or not current_attempt.get('published', True)):
        # Keep observing even when optional page-scope review is toggled while
        # this exact scope is running. A widget rerun must not hide the monitor.
        analysis_attempted = True
        result = _analyse_upload(
            st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
            settings=settings, cache=cache, progress=progress,
            scope=failure['scope'] if retry_requested and failure else None,
            retry=retry_requested, presentation_budget=presentation_budget,
        )
    elif retry_requested:
        analysis_attempted = True
        result = _analyse_upload(
            st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
            settings=settings, cache=cache, scope=failure["scope"], retry=True,
            progress=progress, presentation_budget=presentation_budget,
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
                    progress=progress, presentation_budget=presentation_budget,
                )
        elif result is None:
            st.info("Review and confirm the page scope before starting deep analysis, or turn off this optional review to run automatically.")
    else:
        analysis_attempted = True
        result = _analyse_upload(
            st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
            settings=settings, cache=cache,
            progress=progress, presentation_budget=presentation_budget,
        )
    if not analysis_attempted and failure:
        _render_analysis_failure(st, failure, progress)
        result = (st.session_state.get('analysis_partial')
                  if st.session_state.get('analysis_partial_key') == scope_key else None)
    if result is None:
        if _analysis_failure(st, scope_key) and not retry_button_shown:
            _retry_analysis_button(st, scope_key)
        return
    branding.result_heading(st, result)
    if not is_complete(result):
        # Diagnostics are useful even when mandatory editorial work failed.
        # Never route this download through finalization, PPT QA or rendering.
        from .analysis_download import render_incomplete
        render_incomplete(st, result, scope_key=scope_key)
        return
    with st.expander("Rerun analysis or rebuild presentation", expanded=False):
        st.caption("Reanalysis makes new model requests. Rebuilding PowerPoint reuses the existing analysis.")
        if st.button("Reanalyse PDF (ignore model cache)"):
            result = _analyse_upload(
                st, raw_pdf, scope_key=scope_key, analysis_focus=analysis_focus,
                settings=settings, cache=cache, force=True, progress=progress,
                scope=(st.session_state.get("analysis_scope") if review_scope
                       and st.session_state.get("analysis_scope_key") == scope_key else None),
                presentation_budget=presentation_budget,
            )
            if result is None:
                if not retry_button_shown:
                    _retry_analysis_button(st, scope_key)
                return
        if st.button("Regenerate PowerPoint only"):
            st.session_state["ppt_build_cache"] = {}
            st.session_state["ppt_visual_cache"] = {}
            from .completion_notification import begin_export_run
            begin_export_run(st, scope_key)
            st.caption("Reusing the existing analysis; rebuilding PowerPoint and rerunning export checks.")

    from adaptive_document_agent.utils.timing import record_timing
    from . import result_explorer
    from .finalization import render as render_finalization
    result = render_finalization(st, result, settings, scope_key)
    with record_timing({}, "result_downloads"):
        deliverables.render(st, result, raw_pdf, progress)
    st.divider()
    branding.section_label(st, "03", "Explore the evidence")
    st.caption("Read the findings, inspect the exact chart data, and trace each conclusion back to its source.")
    result_explorer.render(st, result, scope_key)
    _LOGGER.info("Result interface ready: charts=%d observations=%d", len(result.charts), len(result.observations))
