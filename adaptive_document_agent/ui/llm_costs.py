"""Readable stage totals and a downloadable model-call ledger."""

from adaptive_document_agent.services.llm.costs import summarize_usage
from adaptive_document_agent.services.llm.usage_export import export_usage_csv, usage_rows


def render(st, records: list[dict]) -> None:
    if not records:
        return
    summary = summarize_usage(records)
    for total in summary["by_currency"]:
        if total["priced_calls"]:
            st.caption(f"{total['currency']} known cost estimate: {total['known_cost_min']:.4f}–{total['known_cost_max']:.4f} "
                       f"({total['priced_calls']} priced calls; public price snapshot, not provider billing).")
    unknown = sum(row["unknown_cost_calls"] for row in summary["by_currency"])
    unmetered = sum(row["unmetered_attempts"] for row in summary["by_currency"])
    if unknown or unmetered:
        st.caption(f"Cost coverage incomplete: {unknown} calls with unknown cost; {unmetered} failed attempts without metering. Known subtotals are not the full bill.")
    st.caption("Reasoning tokens are part of output tokens. Missing cache/reasoning counters remain unknown. App cache hits make no provider request.")
    with st.expander("Model costs by stage and per call", expanded=False):
        st.dataframe(summary["by_stage"], use_container_width=True)
        st.dataframe(usage_rows(records), use_container_width=True)
        st.download_button("Download model cost details (.csv)", export_usage_csv(records),
                           "llm_cost_details.csv", "text/csv", key="download_llm_cost_details",
                           on_click="ignore")
