"""Professional Streamlit shell over the stable orchestration API."""

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.export import export_csv, export_json, export_markdown
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.routing import create_llm_client
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.hashing import sha256_bytes

from . import analysis, data, overview, quality, sources, technical
from .charts import chart_rows, render_chart
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
    settings = render_sidebar(st)
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

            preview = DocumentOrchestrator(gateway, cache=DiskCache()).preview_scope(
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

                result = DocumentOrchestrator(gateway, cache=DiskCache()).analyse_pdf(
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
    st.download_button("Download Markdown", export_markdown(result), "analysis_report.md", "text/markdown")
    st.download_button("Download JSON", export_json(result), "analysis_data.json", "application/json")
    st.download_button("Download CSV", export_csv(result), "extracted_observations.csv", "text/csv")
