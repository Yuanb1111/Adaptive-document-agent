from __future__ import annotations

from adaptive_document_agent.ui import deployment
from adaptive_document_agent.ui.deployment import cache_for_session, is_public_deployment


def test_public_deployment_flag(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "true")

    assert is_public_deployment() is True


def test_public_sessions_receive_isolated_temporary_caches(monkeypatch) -> None:
    created_names: list[str] = []

    class FakeTemporaryDirectory:
        def __init__(self, *, prefix: str, dir=None, ignore_cleanup_errors: bool = False) -> None:
            self.name = f"{prefix}{len(created_names)}"
            created_names.append(self.name)

    monkeypatch.setattr(deployment.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)
    first_state: dict[str, object] = {}
    second_state: dict[str, object] = {}

    first_cache = cache_for_session(first_state, public_deployment=True)
    repeated_cache = cache_for_session(first_state, public_deployment=True)
    second_cache = cache_for_session(second_state, public_deployment=True)

    assert first_cache.root == repeated_cache.root
    assert first_cache.root != second_cache.root
    assert len(created_names) == 2
