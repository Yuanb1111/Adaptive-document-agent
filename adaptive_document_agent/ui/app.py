"""Professional Streamlit shell over the stable orchestration API."""

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.export import export_pptx_with_report
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.routing import create_llm_client
from adaptive_document_agent.utils.hashing import sha256_bytes

from . import analysis, data, overview, quality, sources, technical
from .charts import chart_rows, render_chart
from .deployment import cache_for_session, is_public_deployment
from .exports import render_report_downloads
from .sidebar import render_sidebar


def run_app() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Streamlit is not installed. Install requirements.txt.") from exc

    st.set_page_config(page_title="Adaptive Document Intelligence Agent", page_icon="📄", layout="wide")
    st.title("Adaptive Document Intelligence Agent")
    st.markdown(
        "Upload a PDF and the Agent will understand the document, discover useful data, "
        "run deterministic calculations, validate results, and preserve page-level evidence."
    )
    public_deployment = is_public_deployment()
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
    uploaded = st.file_uploader("Upload one PDF", type=["pdf"], accept_multiple_files=False)
    if not uploaded:
        st.info("Upload a PDF to begin. You do not need to choose a document type.")
        return
    raw_pdf = uploaded.getvalue()
    scope_key = sha256_bytes(
        "|".join(
            (
                "table-alignment-v9",
                sha256_bytes(raw_pdf),
                analysis_focus.strip(),
                settings.provider.value,
                settings.model,
                settings.base_url or "",
            )
        ).encode("utf-8")
    )
    if st.button("Review analysis scope"):
        if not settings.model:
            st.error("Configure a model before analysis.")
            return
        try:
            gateway = LLMGateway(create_llm_client(settings), settings)
            status = st.status("Preparing analysis scope…", expanded=True)

            def update(stage: str) -> None:
                status.write(stage)

            preview = DocumentOrchestrator(gateway, cache=cache).preview_scope(
                raw_pdf,
                progress=update,
                analysis_focus=analysis_focus,
            )
            st.session_state["analysis_scope"] = preview
            st.session_state["analysis_scope_key"] = scope_key
            st.session_state.pop("analysis_result", None)
            status.update(label="Analysis scope ready", state="complete", expanded=False)
        except Exception as exc:
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
        st.caption(f"Selected {preview.selected_page_count} of {preview.page_count} pages. Deep analysis starts only after confirmation.")
        confirmed = st.checkbox("I confirm these page ranges for deep analysis", key=f"confirm_{scope_key}")
        if st.button("Analyse selected pages", type="primary", disabled=not confirmed):
            try:
                gateway = LLMGateway(create_llm_client(settings), settings)
                status = st.status("Starting analysis…", expanded=True)

                def update_analysis(stage: str) -> None:
                    status.write(stage)

                result = DocumentOrchestrator(gateway, cache=cache).analyse_pdf(
                    raw_pdf,
                    progress=update_analysis,
                    analysis_focus=analysis_focus,
                    scope=preview,
                )
                st.session_state["analysis_result"] = result
                st.session_state["analysis_result_key"] = scope_key
                status.update(label="Analysis complete", state="complete", expanded=False)
            except Exception as exc:
                st.error(f"Analysis could not be completed: {exc}")
                return
    else:
        st.info("Review and confirm the page scope before starting deep analysis.")
    result = st.session_state.get("analysis_result") if st.session_state.get("analysis_result_key") == scope_key else None
    if not result:
        return
    tab_overview, tab_analysis, tab_charts, tab_data, tab_sources, tab_quality, tab_technical = st.tabs(["Overview", "Analysis", "Charts", "Extracted Data", "Sources", "Data Quality", "Technical Details"])
    with tab_overview:
        overview.render(st, result)
    with tab_analysis:
        analysis.render(st, result)
    with tab_charts:
        index = DocumentIndex(result.observations)
        if not result.charts:
            st.info("No chart met the usefulness and evidence thresholds.")
        for plan in result.charts:
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
    st.subheader("Exports & Deliverables")
    from adaptive_document_agent.services.qa_reporter import CriticalQAError

    pptx_bytes: bytes | None = None
    qa_error: CriticalQAError | None = None
    visual_report = None
    from adaptive_document_agent.services.presentation_visual_qa import VisualQAError
    try:
        with st.spinner("Building and verifying PowerPoint…"):
            verified = export_pptx_with_report(
                result, visual_cache=st.session_state.setdefault("ppt_visual_cache", {}),
                build_cache=st.session_state.setdefault("ppt_build_cache", {}),
            )
        pptx_bytes = verified.payload
        visual_report = verified.report
        st.caption(
            f"PowerPoint export: {verified.timings_ms['ppt_export_total'] / 1000:.1f}s; "
            f"build reused: {verified.build_cache_hit}; rendered QA reused: {visual_report.cache_hit}"
        )
        with st.expander("PowerPoint export timing (ms)"):
            st.json(verified.timings_ms)
    except VisualQAError as exc:
        qa_error = exc
        visual_report = exc.report
    except CriticalQAError as exc:
        qa_error = exc
    except Exception as exc:
        qa_error = CriticalQAError(f"PowerPoint generation failed ({type(exc).__name__}). No verified file was produced.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if pptx_bytes:
            st.download_button(
                "Download presentation (.pptx)",
                pptx_bytes,
                "analysis_presentation.pptx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                type="primary",
                use_container_width=True,
            )
        else:
            st.button("Download presentation (.pptx)", disabled=True, use_container_width=True, help="Export blocked by Critical QA")
    render_report_downloads(st, result, (col2, col3, col4), pdf_cache=st.session_state.setdefault("pdf_export_cache", {}))

    if qa_error:
        from adaptive_document_agent.services.export_diagnostics import export_diagnostics
        import json
        qa = export_diagnostics(result, qa_error, visual_report)
        stage = qa["export_error"]["stage"]
        st.error(f"PowerPoint export blocked — {stage}")
        st.markdown(
            "The presentation did not pass the financial or rendered-layout export gate. "
            "No verified PowerPoint file is available. Review the reason below:"
        )
        for err in qa["critical_errors"]:
            st.error(f"[{err['code']}]: {err['message']}")

        with st.expander("🔍 View Detailed QA Audit Report & Artifacts", expanded=False):
            st.json(qa)
            st.download_button(
                "Download complete export diagnostic report (qa_report.json)",
                json.dumps(qa, indent=2),
                "qa_report.json",
                "application/json",
            )

    if visual_report:
        import json
        with st.expander("PowerPoint rendered validation report", expanded=visual_report.status == "failed"):
            st.caption(f"Status: {visual_report.status}; render passes: {visual_report.attempts}; cache reused: {visual_report.cache_hit}")
            for limitation in visual_report.coverage:
                st.caption(limitation)
            st.json(visual_report.to_dict())
            st.download_button("Download visual QA report", json.dumps(visual_report.to_dict(), indent=2),
                               "ppt_visual_qa.json", "application/json")
