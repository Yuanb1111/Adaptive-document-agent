"""Overview result tab."""

import re

from adaptive_document_agent.models import PipelineResult
from .branding import insight_card


def render(st, result: PipelineResult) -> None:
    from adaptive_document_agent.services.executive_brief import display_brief
    try:
        title, items = display_brief(result)
    except ValueError:
        title = "Executive Summary"
        items = []
        st.warning("The saved executive briefing failed its source checks. Showing document context instead.")
    if items:
        st.subheader(_literal(title))
        for item in items:
            st.markdown(f"**{_literal(item.title)}** — {_literal(item.text)}")
            if item.table:
                # Escape all document-derived cells; Markdown cannot load media.
                header = '| ' + ' | '.join(_literal(c) for c in item.table.headers) + ' |'
                divider = '| ' + ' | '.join('---' for _ in item.table.headers) + ' |'
                rows = ['| ' + ' | '.join(_literal(c) for c in row) + ' |' for row in item.table.rows]
                st.markdown('\n'.join([header, divider, *rows]))
            if item.conditions:
                st.markdown(_literal(item.conditions))
            st.caption("Source pages: " + ", ".join(map(str, item.pages)))
        with st.expander("Document context and analysis coverage", expanded=False):
            _context(st, result)
    else:
        if any(w.code == "executive_brief_unavailable" for w in result.validation_warnings):
            st.caption("The final briefing is unavailable for this run. Document context is shown below.")
        _context(st, result)
    if result.profile.data_quality_notes:
        notes = list(dict.fromkeys(result.profile.data_quality_notes))
        st.warning(
            f"{len(notes)} data-quality note(s) may affect interpretation. "
            "Open the details below or use the Data Quality tab for the full audit."
        )
        with st.expander("Data-quality notes", expanded=False):
            for note in notes:
                st.markdown(f"- {note}")
    if result.insights and not items:
        st.subheader("Key findings")
        st.caption("The first findings in report order. Open Analysis for the full narrative and Sources for the evidence.")
        for number, insight in enumerate(result.insights[:3], start=1):
            insight_card(st, insight, number)


def _context(st, result: PipelineResult) -> None:
    coverage = result.profile.source_coverage
    if coverage:
        with st.expander('Source sections and bounded checks', expanded=False):
            st.caption('Page selection records processing extent. It does not certify completeness or business accuracy.')
            st.dataframe([dict(Section=s.title,Pages=f'{s.start_page}–{s.end_page}',
                Status=s.processing_status,Selected=len(s.selected_pages),Evidence=len(s.observation_ids),
                Planned_topics=', '.join(s.planned_topic_ids),Exported_topics=', '.join(s.exported_topic_ids),
                PPT_pages=', '.join(map(str,s.exported_slide_numbers)),Reason='; '.join(s.selection_reasons) or 'Not selected; semantic exclusion reason not recorded')
                for s in coverage.sections],use_container_width=True,hide_index=True)
            for c in coverage.checks:
                st.write(dict(pages=c.pages,status=c.status,question=c.reason,impact=c.decision_impact,finding=c.finding,evidence=c.evidence_quotes))
            st.caption(f'Supplementary calls {coverage.calls_used}/{coverage.max_calls}; at most {coverage.max_supplementary_pages} pages. Full source review remains incomplete.')
            for note in coverage.notes:st.text(note)
    left, middle, right = st.columns(3)
    left.metric("Pages", result.document.page_count)
    middle.metric("Observations", len(result.observations))
    right.metric("Validated analyses", sum(item.result is not None for item in result.analysis_results))
    st.subheader(result.profile.overview_title or result.profile.document_type or "Document overview")
    st.write(result.profile.document_summary or result.profile.document_purpose)
    if result.profile.document_summary_pages:
        st.caption("Summary source pages: " + ", ".join(map(str, result.profile.document_summary_pages)))
    for point in result.profile.overview_points:
        st.markdown(f"- {point}")
    if result.profile.detected_time_periods:
        st.caption("Reporting periods found: " + " · ".join(result.profile.detected_time_periods))
    if result.profile.important_sections:
        st.markdown("**Important sections**")
        st.write(" · ".join(result.profile.important_sections))


def _literal(text: str) -> str:
    """Display source-derived prose as text, without loading Markdown media."""
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>$])", lambda match: "\\" + match.group(0), text)
