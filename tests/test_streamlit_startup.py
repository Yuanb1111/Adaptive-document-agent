"""Production startup contracts, isolated from pytest's already-imported modules."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_fresh(code: str) -> None:
    env = dict(os.environ)
    # Test the shipped project config, not the developer's shell overrides.
    env.pop("STREAMLIT_SERVER_FILE_WATCHER_TYPE", None)
    env.pop("STREAMLIT_SERVER_RUN_ON_SAVE", None)
    env["PUBLIC_DEPLOYMENT"] = "true"
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_production_config_and_secrets_ignore_contract():
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["server"]["fileWatcherType"] == "none"
    assert config["server"]["runOnSave"] is False
    # No security settings or secrets should be bundled with this fix.
    assert set(config) == {"server"}
    for path, ignored in ((".streamlit/secrets.toml", True), (".streamlit/config.toml", False)):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT,
            capture_output=True, text=True,
        )
        assert result.returncode == (0 if ignored else 1), result.stderr


def test_streamlit_effectively_registers_no_source_watchers():
    run_fresh('''
        from pathlib import Path
        from streamlit import config
        from streamlit.runtime.pages_manager import PagesManager
        from streamlit.watcher.local_sources_watcher import LocalSourcesWatcher
        from streamlit.watcher.path_watcher import NoOpPathWatcher, get_default_path_watcher_class

        assert config.get_option("server.fileWatcherType") == "none"
        assert config.get_option("server.runOnSave") is False
        assert get_default_path_watcher_class() is NoOpPathWatcher
        watcher = LocalSourcesWatcher(PagesManager(str(Path("app.py").resolve())))
        try:
            import adaptive_document_agent.ui.app
            watcher.update_watched_modules()
            # With no registrations there are no source-change callbacks to
            # evict application modules while other sessions are importing.
            assert watcher._watched_modules == {}
        finally:
            watcher.close()
    ''')


@pytest.mark.parametrize("restart", range(3))
def test_concurrent_cold_imports_after_process_restart(restart):
    run_fresh('''
        import importlib
        import importlib.abc
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        class NoDeprecatedFitz(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "fitz" or fullname.startswith("fitz."):
                    raise AssertionError("Deprecated fitz import during startup")
        sys.meta_path.insert(0, NoDeprecatedFitz())
        names = (
            "adaptive_document_agent.ui.app",
            "adaptive_document_agent.agent.analysis_planner",
            "adaptive_document_agent.services.export_readiness",
            "adaptive_document_agent.extraction.normalizer",
            "adaptive_document_agent.models.presentation",
            "adaptive_document_agent.services.presentation_layout_qa",
            "adaptive_document_agent.services.pdf_render_layout",
        )
        barrier = Barrier(8)
        def session(_):
            barrier.wait(timeout=20)
            modules = [importlib.import_module(name) for name in names]
            for _ in range(5):
                assert all(importlib.import_module(name) is module
                           for name, module in zip(names, modules))
            return tuple(id(module) for module in modules)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(session, range(8)))
        assert all(result == results[0] for result in results)
        assert "fitz" not in sys.modules
    ''')


@pytest.mark.parametrize("watching", [False, True])
def test_public_homepage_sessions_and_widget_reruns(watching):
    # AppTest renders real Streamlit widgets; the renderer is stubbed here only.
    # Actual LibreOffice readiness/rendering has its own Linux integration test.
    run_fresh(f'''
        from unittest.mock import patch
        from streamlit import config
        from streamlit.testing.v1 import AppTest

        config.set_option("server.fileWatcherType", {"auto" if watching else "none"!r})
        probe = {{"ready": True, "backend": "startup-test", "message": ""}}
        with patch("adaptive_document_agent.services.export_readiness.check_export_readiness", return_value=probe):
            for _ in range(2):
                app = AppTest.from_file("app.py", default_timeout=30).run()
                assert not app.exception, app.exception
                app.text_area[0].input("Compare comparable reporting periods").run()
                assert not app.exception, app.exception
                assert app.text_area[0].value == "Compare comparable reporting periods"
                captions = [item.value for item in app.caption]
                warnings = [item.value for item in app.warning]
                assert any("PowerPoint export environment ready" in value for value in captions)
                if {watching!r}:
                    assert any("Source reload is enabled" in value for value in warnings)
                    assert not any("Source reload: disabled" in value for value in captions)
                else:
                    assert any("Source reload: disabled" in value for value in captions)
                    assert not any("Source reload is enabled" in value for value in warnings)
    ''')
