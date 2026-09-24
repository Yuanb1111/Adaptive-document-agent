"""Top-level result downloads and PowerPoint verification UI."""

from __future__ import annotations

import json

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.services.export import export_pptx_with_report

from .exports import render_report_downloads


def render(st, result: PipelineResult, raw_pdf: bytes, progress) -> None:
    """Render all deliverables before the long result tabs."""
    st.subheader("Downloads")
    st.caption("The main deliverables stay here at the top of the results page.")

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
    export_timings = None
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
        visual_report = verified.report
        export_timings = verified.timings_ms
        progress.finish()
        st.caption(
            f"PowerPoint export: {verified.timings_ms['ppt_export_total'] / 1000:.1f}s; "
            f"build reused: {verified.build_cache_hit}; rendered QA reused: {visual_report.cache_hit}"
        )
    except VisualQAError as exc:
        qa_error = exc
        visual_report = exc.report
    except CriticalQAError as exc:
        qa_error = exc
    except ValueError as exc:
        qa_error = CriticalQAError(f"PowerPoint generation failed: {exc}. No verified file was produced.")
    except Exception as exc:
        qa_error = CriticalQAError(
            f"PowerPoint generation failed ({type(exc).__name__}). No verified file was produced."
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
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
            )
        else:
            st.button(
                "Download presentation (.pptx)",
                disabled=True,
                use_container_width=True,
                help="Export blocked by Critical QA",
            )
    render_report_downloads(
        st,
        result,
        (col2, col3, col4),
        pdf_cache=st.session_state.setdefault("pdf_export_cache", {}),
    )

    if qa_error:
        progress.fail("PowerPoint export blocked")
        from adaptive_document_agent.services.export_diagnostics import export_diagnostics

        qa = export_diagnostics(result, qa_error, visual_report)
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
            )

    if editorial or visual_report:
        with st.expander("Delivery diagnostics", expanded=False):
            for item in editorial:
                st.markdown(f"- {item.slide_id + ': ' if item.slide_id else ''}{item.message}")
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
                )

    if export_timings:
        with st.expander("Export timing", expanded=False):
            st.json(export_timings)
