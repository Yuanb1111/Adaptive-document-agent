"""Evidence-preserving table work and safe timing diagnostics."""

from contextlib import nullcontext
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.utils.timing import record_timing, configure_timing_logging


def test_table_words_are_read_once_per_page_and_layout_is_released(monkeypatch):
    found = SimpleNamespace(
        bbox=(0, 100, 300, 200),
        extract=lambda: [["Metric", "2024", "2025"], ["Sales", "100", "120"]],
        rows=[],
    )
    page = SimpleNamespace(
        find_tables=lambda: [found, found],
        extract_words=Mock(return_value=[]), close=Mock(),
    )
    monkeypatch.setattr("pdfplumber.open", lambda _: nullcontext(SimpleNamespace(pages=[page])))
    monkeypatch.setattr("adaptive_document_agent.extraction.table_extractor.BorderlessTableExtractor.extract", lambda *args: [])
    result = TableExtractor().extract(b"test")
    assert len(result[1]) == 2
    assert result[1][0].raw_cells[1] == ["Sales", "100", "120"]
    assert result[1][0].rows[0].page == 1
    page.extract_words.assert_called_once_with(x_tolerance=2, y_tolerance=2)
    page.close.assert_called_once()


def test_cached_word_geometry_matches_uncached_lookup():
    words = [{"text": "Revenue", "top": 90, "x0": 10, "x1": 70},
             {"text": "other", "top": 300, "x0": 10, "x1": 70}]
    page = SimpleNamespace(extract_words=Mock(return_value=words))
    found = SimpleNamespace(bbox=(0, 100, 300, 200))
    extractor = TableExtractor()
    expected = extractor._context_above(page, found, distance=90)
    assert extractor._context_above(page, found, distance=90, words=words) == expected == "Revenue"
    assert page.extract_words.call_count == 1


def test_timing_logs_failure_without_exception_payload(caplog):
    values = {}
    with caplog.at_level(logging.INFO, logger="adaptive_document_agent.timing"):
        with pytest.raises(ValueError):
            with record_timing(values, "semantic"):
                raise ValueError("secret document or API credential")
    assert values["semantic"] >= 0
    assert "stage_started stage=semantic" in caplog.text
    assert "status=failed" in caplog.text
    assert "secret document" not in caplog.text


def test_timing_configuration_is_idempotent_and_does_not_enable_sdk_logs():
    logger = logging.getLogger("adaptive_document_agent.timing")
    original = logger.handlers[:], logger.level, logger.propagate
    root_level = logging.getLogger().level
    try:
        configure_timing_logging()
        handlers = logger.handlers[:]
        configure_timing_logging()
        assert logger.handlers == handlers
        assert logger.level == logging.INFO and not logger.propagate
        assert logging.getLogger().level == root_level
    finally:
        for handler in logger.handlers:
            if handler not in original[0]:
                handler.close()
        logger.handlers, logger.level, logger.propagate = original
