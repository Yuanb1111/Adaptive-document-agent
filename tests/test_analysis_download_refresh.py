"""Expired media can be registered again from retained partial analysis only."""
from unittest.mock import Mock
import json
import pytest

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.ui import analysis_download, app
from tests.test_analysis_export_diagnostics import DownloadUI, _result
from tests.test_failed_analysis_reruns import flow


def test_partial_json_download_needs_no_presentation_or_export_checks():
    result, ui = _result(), DownloadUI()
    result.pipeline_state, result.retry_from = 'partial', 'reporting'
    result.validation_warnings.append(ValidationIssue(code='company_introduction_unavailable',
        message='Two meanings must be split.', stage='presentation', severity='error'))
    before = result.model_dump()
    analysis_download.render_incomplete(ui, result, scope_key='scope')
    payload = json.loads(ui.downloads['analysis_data.json'])
    assert payload['pipeline_state'] == 'partial' and payload['presentation_plan'] is None
    assert payload['validation_warnings'][0]['message'] == 'Two meanings must be split.'
    assert result.model_dump() == before
    assert ui.download_options['analysis_data.json']['on_click'] == 'ignore'


def test_refresh_recreates_expired_streamlit_media_without_model_or_ppt_work(monkeypatch):
    from streamlit.runtime import media_file_manager
    from streamlit.runtime.media_file_storage import MediaFileStorageError
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
    monkeypatch.setattr(media_file_manager, '_get_session_id', lambda: 'retained-result-session')
    storage = MemoryMediaFileStorage('/media')
    manager = media_file_manager.MediaFileManager(storage)
    result, ui = _result(), DownloadUI()
    result.pipeline_state = 'partial'
    links = []
    def download(label, data, filename, mime, **kwargs):
        links.append(manager.add(data, mime, 'json-download', file_name=filename, is_for_static_download=True))
    ui.download_button = download
    analysis_download.render(ui, result)
    file_name = links[-1].rsplit('/', 1)[1]
    original = storage.get_file(file_name).content
    manager.clear_session_refs('retained-result-session')
    manager.remove_orphaned_files()
    manager.remove_orphaned_files()
    with pytest.raises(MediaFileStorageError):
        storage.get_file(file_name)
    # The refresh fragment re-registers bytes from the retained result even
    # when Streamlit has removed the earlier media object after disconnect.
    analysis_download.render(ui, result)
    assert storage.get_file(links[-1].rsplit('/', 1)[1]).content == original
    assert json.loads(original)['pipeline_state'] == 'partial'


def test_incomplete_app_download_precedes_finalization_and_skips_ppt(flow, monkeypatch):
    flow.result.pipeline_state, flow.result.retry_from = 'partial', 'reporting'
    flow.result.validation_warnings.append(ValidationIssue(code='company_introduction_unavailable',
        message='Split independently checkable meanings.', stage='presentation'))
    flow.outcomes.clear()
    flow.outcomes.append(flow.result)
    flow.st.fragment.side_effect = lambda function=None, **kwargs: function or (lambda f: f)
    finalization = Mock(side_effect=AssertionError('Do not finalize incomplete output'))
    monkeypatch.setattr('adaptive_document_agent.ui.finalization.render', finalization)
    for _ in range(2):
        app.run_app()
    assert len(flow.attempts) == 1
    finalization.assert_not_called()
    app.deliverables.render.assert_not_called()
    downloads = [c for c in flow.st.download_button.call_args_list
                 if len(c.args) > 2 and c.args[2] == 'analysis_data.json']
    assert len(downloads) == 2
    assert all(json.loads(c.args[1])['pipeline_state'] == 'partial' for c in downloads)


def test_json_serialization_failure_is_local_and_redacted():
    ui = DownloadUI()
    ui.warning = Mock()
    analysis_download.render(ui, _result(), exporter=Mock(side_effect=ValueError('secret source path')))
    assert not ui.downloads
    assert 'ValueError' in ui.warning.call_args.args[0]
    assert 'secret source path' not in str(ui.warning.call_args)
