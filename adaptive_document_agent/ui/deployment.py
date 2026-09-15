"""Runtime safeguards for local and publicly hosted Streamlit sessions."""

import os
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from adaptive_document_agent.utils.caching import DiskCache

_SESSION_CACHE_KEY = "_adaptive_document_cache_tempdir"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_public_deployment() -> bool:
    """Return whether public-hosting safeguards should be enforced."""

    return os.getenv("PUBLIC_DEPLOYMENT", "false").strip().casefold() in _TRUE_VALUES


def cache_for_session(
    session_state: MutableMapping[str, Any],
    *,
    public_deployment: bool | None = None,
    temporary_root: str | Path | None = None,
) -> DiskCache:
    """Return a persistent local cache or an isolated temporary hosted cache."""

    public_deployment = is_public_deployment() if public_deployment is None else public_deployment
    if not public_deployment:
        return DiskCache(Path(os.getenv("CACHE_DIR", ".adaptive_document_cache")))

    temporary_directory = session_state.get(_SESSION_CACHE_KEY)
    if temporary_directory is None:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="adaptive-document-agent-",
            dir=temporary_root,
            ignore_cleanup_errors=True,
        )
        session_state[_SESSION_CACHE_KEY] = temporary_directory
    return DiskCache(Path(temporary_directory.name))
