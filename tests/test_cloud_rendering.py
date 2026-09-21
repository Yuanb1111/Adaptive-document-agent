"""Portable rendering contracts; real Linux tests are opt-in and run in CI."""

import io
import os
from pathlib import Path
import subprocess
import sys

import fitz
import pytest
from pptx import Presentation
from pptx.util import Inches

from adaptive_document_agent.services import presentation_rendering as rendering
from adaptive_document_agent.services import presentation_visual_qa as qa
from adaptive_document_agent.services import libreoffice_rendering as lo
from adaptive_document_agent.services import export_readiness as readiness
from adaptive_document_agent.services.export_diagnostics import export_diagnostics
from adaptive_document_agent.services.pdf_render_layout import pdf_rendered_pages
from adaptive_document_agent.services.qa_reporter import CriticalQAError, QAItem, QAReport
from tests.ppt_render_stub import LocalRenderStub
from tests.test_p2_visual_qa import deck_bytes
from tests.test_pptx_export import _result


@pytest.fixture
def clean_renderer_env(monkeypatch):
    for key in ("PPTX_QA_BACKEND", "PPTX_QA_NODE", "PPTX_QA_ARTIFACT_MODULE", "PPTX_QA_LIBREOFFICE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(rendering.shutil, "which", lambda _: None)


def test_auto_selects_installed_libreoffice_without_codex_paths(clean_renderer_env, monkeypatch):
    monkeypatch.setattr(rendering.shutil, "which", lambda name: "/usr/bin/libreoffice" if name == "libreoffice" else None)
    sentinel = object()
    monkeypatch.setattr(lo, "LibreOfficeRenderer", lambda path: sentinel if path == "/usr/bin/libreoffice" else None)
    assert rendering.configured_renderer() is sentinel


def test_partial_explicit_artifact_configuration_never_silently_falls_back(clean_renderer_env, monkeypatch):
    monkeypatch.setenv("PPTX_QA_NODE", "/configured/node")
    monkeypatch.setattr(rendering.shutil, "which", lambda _: "/usr/bin/libreoffice")
    with pytest.raises(rendering.RenderingError, match="both"):
        rendering.configured_renderer()


def test_explicit_libreoffice_ignores_stale_artifact_paths(clean_renderer_env, monkeypatch):
    monkeypatch.setenv("PPTX_QA_BACKEND", "libreoffice")
    monkeypatch.setenv("PPTX_QA_NODE", "C:/desktop-only/node.exe")
    monkeypatch.setenv("PPTX_QA_LIBREOFFICE", "/usr/bin/libreoffice")
    monkeypatch.setattr(lo, "LibreOfficeRenderer", lambda path: path)
    assert rendering.configured_renderer() == "/usr/bin/libreoffice"


def test_missing_cloud_dependency_has_deployment_remediation(clean_renderer_env):
    with pytest.raises(rendering.RenderingError, match="packages.txt"):
        rendering.configured_renderer()


def test_invalid_backend_fails_closed(clean_renderer_env, monkeypatch):
    monkeypatch.setenv("PPTX_QA_BACKEND", "remote")
    with pytest.raises(rendering.RenderingError, match="must be"):
        rendering.configured_renderer()


def test_startup_probe_is_cached_per_runtime_and_does_not_include_document(monkeypatch):
    renderer = LocalRenderStub()
    monkeypatch.setattr(readiness, "configured_renderer", lambda: renderer)
    cache = {}
    assert readiness.check_export_readiness(cache)["ready"]
    assert readiness.check_export_readiness(cache)["ready"]
    assert renderer.calls == 1
    renderer.identity = "updated"
    assert readiness.check_export_readiness(cache)["ready"] and renderer.calls == 2


def test_startup_probe_failure_is_not_cached(monkeypatch):
    def missing():
        raise rendering.RenderingError("Install packages.txt")
    monkeypatch.setattr(readiness, "configured_renderer", missing)
    cache = {}
    assert not readiness.check_export_readiness(cache)["ready"] and not cache


def test_complete_report_contains_visual_failure_even_when_financial_qa_passes():
    visual = qa.VisualQAReport(issues=[qa.VisualIssue(0, "RENDERING_BLOCKED", "critical", message="Missing runtime")])
    error = qa.VisualQAError(visual)
    error.financial_report = QAReport(document_title="Generic")
    report = export_diagnostics(_result(), error, visual)
    assert report["is_export_blocked"]
    assert not report["financial_qa"]["critical_errors"]
    assert report["critical_errors"][0]["code"] == "RENDERING_BLOCKED"
    assert report["visual_qa"]["status"] == "failed"
    assert report["export_error"]["stage"] == "rendering"


def test_financial_error_uses_original_snapshot_not_a_second_repair(monkeypatch):
    from adaptive_document_agent.services import export_diagnostics as diagnostics
    original = QAReport(document_title="Generic", critical_errors=[QAItem(code="original", severity="CRITICAL", message="Blocked")], is_export_blocked=True)
    monkeypatch.setattr(diagnostics, "run_comprehensive_qa", lambda *a, **k: pytest.fail("Unexpected second QA pass"))
    report = diagnostics.export_diagnostics(_result(), CriticalQAError("Blocked", financial_report=original))
    assert report["critical_errors"][0]["code"] == "original"
    assert report["export_error"]["stage"] == "financial"


def test_generation_error_is_not_misreported_as_passed():
    error = CriticalQAError("Build failed", financial_report=QAReport(document_title="Generic"))
    report = export_diagnostics(_result(), error)
    assert report["is_export_blocked"] and report["export_error"]["stage"] == "generation"


def make_pdf(tmp_path, *, include_text=True, pages=1):
    path = tmp_path / "render.pdf"
    with fitz.open() as pdf:
        for _ in range(pages):
            page = pdf.new_page(width=720, height=432)
            if include_text:
                page.insert_text((72, 88), "Revenue 10,350,986 CNY", fontsize=12)
            else:
                page.draw_rect(fitz.Rect(10, 10, 40, 40), fill=(0, 0, 0))
        pdf.save(path)
    return path


def test_pdf_adapter_uses_real_pixels_and_discloses_native_geometry(tmp_path):
    raw = deck_bytes()
    pages = pdf_rendered_pages(raw, make_pdf(tmp_path))
    assert pages[0].layout["geometrySource"] == "ooxml"
    assert pages[0].layout["elements"][0]["renderedTextPresent"]
    assert not [i for i in qa.inspect_pages(raw, pages) if i.severity == "critical"]


def test_pdf_adapter_missing_visible_text_still_blocks(tmp_path):
    raw = deck_bytes()
    pages = pdf_rendered_pages(raw, make_pdf(tmp_path, include_text=False))
    assert any(i.code == "MISSING_RENDER_TEXT" for i in qa.inspect_pages(raw, pages))


def test_pdf_adapter_wrong_page_count_blocks(tmp_path):
    with pytest.raises(rendering.RenderingError, match="omitted or added"):
        pdf_rendered_pages(deck_bytes(), make_pdf(tmp_path, pages=2))


@pytest.mark.parametrize("exit_code,expected", [(78, "isolation"), (1, "failed to render")])
def test_linux_worker_failure_is_not_certified(tmp_path, monkeypatch, exit_code, expected):
    renderer = object.__new__(lo.LibreOfficeRenderer)
    renderer.timeout = 1
    killed = []
    class Worker:
        pid = 12345
        def __init__(self, command, **kwargs):
            assert isinstance(command, list) and kwargs["shell"] is False and kwargs["start_new_session"]
            assert "LLM_API_KEY" not in kwargs["env"]
        def wait(self, timeout):
            return exit_code
    monkeypatch.setattr(lo.subprocess, "Popen", Worker)
    monkeypatch.setattr(lo.os, "killpg", lambda *args: killed.append(args), raising=False)
    monkeypatch.setattr(lo.signal, "SIGKILL", 9, raising=False)
    with pytest.raises(rendering.RenderingError, match=expected):
        renderer._run(["/trusted/renderer"], tmp_path)
    assert killed == [(12345, 9)]


def test_worker_timeout_cleans_only_owned_group(tmp_path, monkeypatch):
    renderer = object.__new__(lo.LibreOfficeRenderer)
    renderer.timeout = .1
    killed = []
    class Worker:
        pid = 123
        calls = 0
        def __init__(self, *a, **k):
            pass
        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("renderer", timeout)
            return -9
    monkeypatch.setattr(lo.subprocess, "Popen", Worker)
    monkeypatch.setattr(lo.os, "killpg", lambda *args: killed.append(args), raising=False)
    monkeypatch.setattr(lo.signal, "SIGKILL", 9, raising=False)
    with pytest.raises(rendering.RenderingError, match="timed out"):
        renderer._run(["/trusted/renderer"], tmp_path)
    assert killed == [(123, 9)]


@pytest.mark.skipif(not os.getenv("PPTX_QA_LIBREOFFICE_INTEGRATION"), reason="Real Linux LibreOffice integration, required in deployment CI")
def test_real_linux_renderer_network_policy_and_native_chart_export(tmp_path, monkeypatch):
    assert sys.platform == "linux"
    monkeypatch.delenv("PPTX_QA_NODE", raising=False)
    monkeypatch.delenv("PPTX_QA_ARTIFACT_MODULE", raising=False)
    monkeypatch.setenv("PPTX_QA_BACKEND", "libreoffice")
    renderer = rendering.configured_renderer()
    renderer._run(["--probe"], tmp_path)
    assert readiness.check_export_readiness({})["ready"]
    raw = deck_bytes(chart=True)
    verified = qa.verify_presentation(raw, renderer=renderer)
    assert verified.payload == raw and verified.report.facts_preserved
    assert "OOXML" in " ".join(verified.report.coverage)
    # Exercise the actual application template, not just a blank smoke deck.
    from adaptive_document_agent.services.export import export_pptx_with_report
    generated = export_pptx_with_report(_result(), renderer=renderer)
    assert generated.report.status in {"passed", "passed_with_warnings"}
    assert generated.report.facts_preserved
