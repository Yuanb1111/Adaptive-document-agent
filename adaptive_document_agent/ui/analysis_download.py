"""Re-register JSON downloads without rerunning analysis or presentation export."""
import logging

from adaptive_document_agent.services.export import export_json


def _render(st, result, diagnostics, key, exporter):
    st.caption('Complete analysis and source evidence; may contain document content.')
    # Clicking refresh reruns only this fragment and registers the file again.
    # It does not click a model retry or rebuild the presentation.
    st.button('Refresh JSON download link', key=key + '_refresh',
              help='Use after sleep or reconnection while this result session is still available. '
                   'Recreates the download from the retained result without model requests.')
    try:
        payload = (exporter(result, pptx_export_diagnostics=diagnostics)
                   if diagnostics is not None else exporter(result))
    except Exception as exc:
        error_type = type(exc).__name__
        logging.getLogger(__name__).warning('JSON export failed (%s)', error_type)
        st.button('Download analysis data (.json)', disabled=True, use_container_width=True)
        st.warning(f'JSON export is unavailable ({error_type}). Other downloads are unaffected.')
        return
    st.download_button('Download analysis data (.json)', payload, 'analysis_data.json',
                       'application/json', key=key, use_container_width=True, on_click='ignore')


def render(st, result, *, diagnostics=None, key='analysis_json_download', exporter=None):
    """Result lives in the fragment closure; link refresh performs no pipeline work."""
    st.fragment(_render)(st, result, diagnostics, key, exporter or export_json)


def render_incomplete(st, result, *, scope_key):
    st.warning('This analysis is incomplete. Download the retained data and diagnostics below. '
               'Use Retry analysis (reuse successful cache) to continue; PowerPoint remains blocked.')
    render(st, result, key='analysis_json_' + scope_key)
    failures = [issue for issue in result.validation_warnings
                if issue.severity == 'error' or issue.code == 'company_introduction_unavailable']
    if failures:
        with st.expander('Analysis failure details', expanded=False):
            for issue in failures:
                st.text(issue.message)
