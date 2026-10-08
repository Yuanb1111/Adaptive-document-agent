"""Load only the requested result view, with bounded chart rendering."""

import inspect
from math import ceil

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.utils.timing import record_timing

from . import analysis, data, overview, quality, sources, technical
from .charts import chart_rows, render_chart

VIEW_LABELS = ("Overview", "Analysis", "Charts", "Extracted Data", "Sources", "Data Quality", "Technical Details")
CHARTS_PER_PAGE = 5


def render(st, result, scope_key):
    """Use tracked tabs when supported; older Streamlit uses a view selector."""
    key = f"result_view_{scope_key}"
    if "on_change" in inspect.signature(st.tabs).parameters:
        tabs = st.tabs(list(VIEW_LABELS), key=key, on_change="rerun")
        for label, tab in zip(VIEW_LABELS, tabs):
            if tab.open:
                with tab:
                    _render_view(st, result, label, scope_key)
    else:
        # Streamlit 1.53 tabs eagerly execute even collapsed/hidden content.
        label = st.segmented_control("Explore the evidence", VIEW_LABELS,
                                     default="Overview", key=key)
        _render_view(st, result, label if label in VIEW_LABELS else "Overview", scope_key)


def _render_view(st, result, label, scope_key):
    with record_timing({}, "result_view_" + label.lower().replace(" ", "_")):
        if label == "Charts":
            _render_charts(st, result, scope_key)
        else:
            modules = {"Overview": overview, "Analysis": analysis, "Extracted Data": data,
                       "Sources": sources, "Data Quality": quality, "Technical Details": technical}
            if label == "Technical Details" and st.session_state.get("analysis_result_reused"):
                st.caption("Reused analysis result: the ledger below records its original generation, not new model charges for this view.")
            modules[label].render(st, result)


def _render_charts(st, result, scope_key):
    count = len(result.charts)
    if not count:
        st.info("No chart met the usefulness and evidence thresholds.")
        return
    pages = ceil(count / CHARTS_PER_PAGE)
    page = st.selectbox(
        "Chart page", range(pages), key=f"chart_page_{scope_key}",
        format_func=lambda value: f"{value + 1} / {pages}",
    ) if pages > 1 else 0
    start = page * CHARTS_PER_PAGE
    st.caption(f"{count} validated visual(s), shown in analytical order. Showing {start + 1}–{min(start + CHARTS_PER_PAGE, count)}.")
    index = DocumentIndex(result.observations)
    for chart_index, plan in enumerate(result.charts[start:start + CHARTS_PER_PAGE], start=start):
        with st.expander(f"{chart_index + 1}. {plan.title}", expanded=chart_index == start):
            style_labels = {"line": "Line", "bar": "Vertical bar", "horizontal_bar": "Horizontal bar",
                            "area": "Area", "pie": "Pie", "scatter": "Scatter", "table": "Data table"}
            available = plan.available_chart_types or [plan.chart_type]
            selected_style = st.selectbox(
                f"Chart style — {plan.title}", available,
                format_func=lambda value: style_labels.get(value, value), key=f"chart_style_{scope_key}_{plan.id}",
            )
            show_labels = st.toggle("Show values directly on chart", value=True, key=f"chart_labels_{scope_key}_{plan.id}")
            st.plotly_chart(render_chart(plan, index, chart_type=selected_style, show_data_labels=show_labels),
                            width="stretch")
            st.caption(f"Source pages: {', '.join(map(str, plan.source_pages))}")
            with st.expander("View the exact data used in this visual"):
                st.dataframe(chart_rows(plan, index), width="stretch", hide_index=True)
