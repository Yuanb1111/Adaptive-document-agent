"""Background table extraction preserves exact scope and drains on cancellation."""
from concurrent.futures import CancelledError
from contextlib import ExitStack, nullcontext
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adaptive_document_agent.agent.table_extraction_task import prepare_table_extraction
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.services.analysis_deadline import AnalysisTimeLimitExceeded


def test_prepared_task_runs_existing_extractor_api_with_a_private_scope_copy(monkeypatch):
    started, release = Event(), Event()
    calls = []

    def extract(self, raw, *, page_numbers=None):
        calls.append((raw, page_numbers))
        started.set()
        assert release.wait(3)
        self.raw_tables_by_page = {2: ['raw']}
        self.source_inventory_by_page = {2: {'status': 'checked'}}
        return {2: ['table']}

    monkeypatch.setattr(TableExtractor, 'extract', extract)
    scope = {2}
    with ExitStack() as resources:
        task = prepare_table_extraction(b'pdf-bytes', scope, resources=resources)
        scope.add(3)
        assert started.wait(3)
        release.set()
        extractor, tables = task.result()
    assert calls == [(b'pdf-bytes', {2})]
    assert tables == {2: ['table']}
    assert extractor.raw_tables_by_page == {2: ['raw']}
    assert extractor.source_inventory_by_page == {2: {'status': 'checked'}}


def test_cancelled_extractor_does_not_open_pdf(monkeypatch):
    import pdfplumber

    opened = Event()
    monkeypatch.setattr(pdfplumber, 'open', lambda _: opened.set())
    cancelled = Event()
    cancelled.set()
    with pytest.raises(CancelledError, match='cancelled'):
        TableExtractor(cancelled=cancelled).extract(b'not-a-pdf', page_numbers={1})
    assert not opened.is_set()


def test_deadline_is_checked_between_selected_pages_and_propagates(monkeypatch):
    import pdfplumber

    pages = [
        SimpleNamespace(bbox=(0, 0, 10, 10), cropbox=(0, 0, 10, 10),
                        find_tables=lambda: [], close=Mock()),
        SimpleNamespace(bbox=(0, 0, 10, 10), cropbox=(0, 0, 10, 10),
                        find_tables=lambda: [], close=Mock()),
    ]
    monkeypatch.setattr(pdfplumber, 'open', lambda _: nullcontext(SimpleNamespace(pages=pages)))
    monkeypatch.setitem(__import__('sys').modules, 'pymupdf', None)
    monkeypatch.setitem(__import__('sys').modules, 'pypdfium2', None)
    monkeypatch.setattr(
        'adaptive_document_agent.extraction.table_extractor.BorderlessTableExtractor.extract',
        lambda *args: [])
    monkeypatch.setattr(
        'adaptive_document_agent.extraction.source_grid_recovery.recover_source_grids',
        lambda *args, **kwargs: [])
    checks = 0

    def check_deadline():
        nonlocal checks
        checks += 1
        if checks == 5:  # before processing selected page 2
            raise AnalysisTimeLimitExceeded(60)

    with pytest.raises(AnalysisTimeLimitExceeded):
        TableExtractor(check_deadline=check_deadline).extract(b'pdf', page_numbers={1, 2})
    assert checks == 5
    pages[0].close.assert_called_once_with()
    pages[1].close.assert_not_called()
