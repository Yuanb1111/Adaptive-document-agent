"""Top-level result downloads and PowerPoint verification UI."""

from __future__ import annotations

import json

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.services.export import export_pptx_with_report

from .exports import render_report_downloads


def render(st, result: PipelineResult, raw_pdf: bytes, progress) -> None:
    """Render all deliverables before the long result tabs."""
    st.subheader("Your presentation")
    st.caption("Download PowerPoint here, then explore the analysis and supporting evidence below.")

    from adaptive_document_agent.services.presentation_editorial import review_presentation

    editorial = review_presentation(result.presentation_plan, result)
    degraded = any(item.code in {"presentation_degraded", "presentation_legacy"} for item in editorial)
    legacy = result.presentation_plan is None
    if legacy:
        st.warning(
            "PowerPoint uses the legacy export because no validated presentation plan is available. "
            "Treat this file as a draft."
        )
    elif degraded:
        st.warning("PowerPoint is an evidence-only fallback. Its narrative may still need review.")
    elif editorial:
        st.warning(f"PowerPoint has {len(editorial)} editorial finding(s). See delivery diagnostics for details.")

    artwork = None
    artwork_error = None
    with st.expander("PowerPoint options", expanded=False):
        st.caption(
            "Optionally use a static PNG/JPEG under 8 MB for the cover and overview. "
            "The image stays in the local PowerPoint export and is not sent to a model."
        )
        uploaded_artwork = st.file_uploader(
            "Cover and overview illustration",
            type=["png", "jpg", "jpeg"],
            key=f"ppt_artwork_{result.document.sha256}",
        )
        if uploaded_artwork is not None:
            from adaptive_document_agent.services.presentation_artwork import validate_artwork

            try:
                artwork = validate_artwork(uploaded_artwork.getvalue())
            except ValueError as exc:
                artwork_error = str(exc)
                st.error(artwork_error)

    from adaptive_document_agent.services.qa_reporter import CriticalQAError
    from adaptive_document_agent.services.presentation_visual_qa import VisualQAError

    pptx_bytes: bytes | None = None
    qa_error: CriticalQAError | None = None
    visual_report = None
    preflight_report = None
    export_timings = None
    outcome = 'export_blocked'
    try:
        if artwork_error:
            raise CriticalQAError(artwork_error)
        with st.spinner("Building and verifying PowerPoint…"):
            verified = export_pptx_with_report(
                result,
                visual_cache=st.session_state.setdefault("ppt_visual_cache", {}),
                build_cache=st.session_state.setdefault("ppt_build_cache", {}),
                artwork=artwork,
                source_pdf=raw_pdf,
                progress=progress.update,
            )
        pptx_bytes = verified.payload
        if not pptx_bytes:
            raise ValueError("The verified export returned an empty presentation")
        visual_report = verified.report
        preflight_report = getattr(verified, "preflight_report", None)
        export_timings = verified.timings_ms
        result.export_timings_ms = dict(export_timings)

    except VisualQAError as exc:
        qa_error = exc
        visual_report = exc.report
        preflight_report = getattr(exc, "preflight_report", None)
    except CriticalQAError as exc:
        qa_error = exc
        preflight_report = getattr(exc, "preflight_report", None)
    except ValueError as exc:
        outcome = 'export_failed'
        preflight_report = getattr(exc, "preflight_report", None)
        qa_error = CriticalQAError(f"PowerPoint generation failed: {exc}. No verified file was produced.",
                                  financial_report=getattr(exc, "financial_report", None),
                                  preflight_report=preflight_report)
    except Exception as exc:
        outcome = 'export_failed'
        preflight_report = getattr(exc, "preflight_report", None)
        qa_error = CriticalQAError(
            f"PowerPoint generation failed ({type(exc).__name__}). No verified file was produced.",
            financial_report=getattr(exc, "financial_report", None), preflight_report=preflight_report,
        )
    except BaseException:
        from .completion_notification import queue_outcome
        queue_outcome(st, 'export_interrupted')
        raise

    with st.container(border=True):
        summary_column, download_column = st.columns([1.65, 1], gap="large")
        with summary_column:
            st.caption("POWERPOINT · PRIMARY OUTPUT")
            st.write(result.presentation_plan.title if result.presentation_plan else result.report_plan.title)
            if pptx_bytes:
                st.caption("Export checks completed. Review the findings and any limitations before sharing.")
            else:
                st.caption("A verified presentation is not available. See the export details below.")
        with download_column:
            if pptx_bytes:
                label = (
                    "Download legacy draft (.pptx)"
                    if legacy
                    else "Download evidence-only draft (.pptx)"
                    if degraded
                    else "Download presentation (.pptx)"
                )
                st.download_button(
                    label,
                    pptx_bytes,
                    "analysis_presentation.pptx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    type="primary",
                    use_container_width=True,
                    on_click="ignore",
                )
            else:
                st.button(
                    "Download presentation (.pptx)",
                    disabled=True,
                    use_container_width=True,
                    help="Export blocked by Critical QA",
                )
    qa = None
    if qa_error:
        from .completion_notification import notify_outcome
        notify_outcome(st, outcome)
        progress.fail("PowerPoint export blocked")
        from adaptive_document_agent.services.export_diagnostics import export_diagnostics

        # Capture this attempt before analysis JSON is serialized. The same
        # snapshot is used by the separate QA download, without changing the
        # analysis result or the inputs used by the native build cache.
        qa = export_diagnostics(result, qa_error, visual_report, preflight_report)
    with st.expander("Other formats · Markdown, PDF, CSV & JSON", expanded=False):
        st.caption("Read the report separately or work with the extracted data and source evidence.")
        render_report_downloads(
            st,
            result,
            tuple(st.columns(3)),
            pdf_cache=st.session_state.setdefault("pdf_export_cache", {}),
            pptx_export_diagnostics=qa,
        )
    if qa is not None:
        stage = qa["export_error"]["stage"]
        st.error(
            f"PowerPoint export blocked at the {stage} check. "
            f"{len(qa['critical_errors'])} critical issue(s) require attention."
        )
        with st.expander("PowerPoint blocker details", expanded=False):
            for err in qa["critical_errors"]:
                st.markdown(f"- **[{err['code']}]** {err['message']}")
            st.download_button(
                "Download complete export diagnostic report (qa_report.json)",
                json.dumps(qa, indent=2),
                "qa_report.json",
                "application/json",
                on_click="ignore",
            )

    if editorial or visual_report or preflight_report:
        with st.expander("Delivery diagnostics", expanded=False):
            for item in editorial:
                st.markdown(f"- {item.slide_id + ': ' if item.slide_id else ''}{item.message}")
            if preflight_report:
                st.caption(f"Native preflight: {preflight_report.status}")
                for issue in preflight_report.issues:
                    st.write(str(issue))
                st.download_button(
                    "Download preflight QA report",
                    json.dumps(preflight_report.to_dict(), indent=2),
                    "ppt_preflight_qa.json",
                    "application/json",
                    on_click="ignore",
                )
            if visual_report:
                st.caption(
                    f"Rendered validation: {visual_report.status}; passes: {visual_report.attempts}; "
                    f"cache reused: {visual_report.cache_hit}"
                )
                for limitation in visual_report.coverage:
                    st.caption(limitation)
                st.download_button(
                    "Download visual QA report",
                    json.dumps(visual_report.to_dict(), indent=2),
                    "ppt_visual_qa.json",
                    "application/json",
                    on_click="ignore",
                )

    if export_timings:
        with st.expander("Export timing", expanded=False):
            st.caption(
                f"PowerPoint export: {export_timings['ppt_export_total'] / 1000:.1f}s; "
                f"build reused: {verified.build_cache_hit}; rendered QA reused: {visual_report.cache_hit}"
            )
            st.json(export_timings)

    if pptx_bytes and qa_error is None:
        progress.finish()
        from .completion_notification import notify_export_ready
        incomplete_intro = any(w.code == 'company_introduction_unavailable' for w in result.validation_warnings)
        qa_warnings = bool(verified.report.issues or preflight_report and preflight_report.status == 'passed_with_warnings')
        custom_review = any(c.status != 'satisfied' for c in result.customization_report)
        notify_export_ready(st, verified, needs_review=bool(legacy or degraded or editorial or incomplete_intro or qa_warnings or custom_review))
    from .customization import render as render_customization
    render_customization(st, result)
