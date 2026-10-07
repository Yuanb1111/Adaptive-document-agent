"""Opt-in browser notices for verified, downloadable PowerPoint exports.

The frameless v2 component runs in the app origin. Its preferences stay in the
browser, so changing them never interrupts a running Streamlit script.
"""

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4


@lru_cache(maxsize=1)
def _asset_sources() -> dict[str, str]:
    """Cache immutable files, never a renderer tied to a Streamlit runtime."""
    assets = Path(__file__).with_name("assets")
    return {kind: (assets / f"completion_notification.{suffix}").read_text(encoding="utf-8")
            for kind, suffix in (("html", "html"), ("css", "css"), ("js", "mjs"))}


def _component():
    from streamlit.components.v2 import component

    # The public API registers in the current runtime. Re-registering the same
    # definition is idempotent; a process-wide cached renderer is not safe when
    # Streamlit creates another runtime (including separate AppTest sessions).
    return component("presentation_completion_notice", **_asset_sources())


def render_settings(st) -> None:
    """Mount before upload so the user can opt into silent completion notices."""
    try:
        renderer = _component()
    except ImportError:
        st.caption("Browser notifications require Streamlit 1.53 or newer. Progress remains available on this page.")
        return
    renderer(data={"mode": "settings"}, key="presentation_notification_settings")


def begin_export_run(st, scope_key: str) -> None:
    """Start a notification cycle only for an explicit PowerPoint rebuild click.

    Bind it to the current analysis attempt so a later reanalysis cannot inherit
    an older export cycle. Cache/widget reruns never call this function.
    """
    attempt = st.session_state.get("analysis_attempts", {}).get(scope_key, {})
    analysis_run = attempt.get("id") if attempt.get("state") == "complete" else None
    st.session_state.setdefault("ppt_notification_export_runs", {})[scope_key] = {
        "id": uuid4().hex, "analysis_run": analysis_run,
    }


def notify_export_ready(st, verified) -> None:
    """Emit only after the download button exists and progress reaches 100%.

    The attempt id changes only when analysis actually starts. Browser state
    remembers that id when a refreshed server session only has cached content,
    while explicit new attempts may notify again for identical output.
    """
    if not verified.payload or verified.report.status != "passed":
        return
    keys = list(st.session_state.get("ppt_build_cache", {}))
    identity = (keys[0] if len(keys) == 1 else
                getattr(verified.report, "output_sha256", "") or sha256(verified.payload).hexdigest())
    event_id = sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    scope_key = st.session_state.get("analysis_result_key")
    attempt = st.session_state.get("analysis_attempts", {}).get(scope_key, {})
    run_id = attempt.get("id") if attempt.get("state") == "complete" else None
    export_run = st.session_state.get("ppt_notification_export_runs", {}).get(scope_key)
    if export_run and export_run["analysis_run"] == run_id:
        run_id = f"{run_id or 'cached'}:export:{export_run['id']}"
    try:
        renderer = _component()
    except ImportError:
        return
    renderer(data={"mode": "complete", "event_id": event_id, "run_id": run_id}, key="presentation_notification_event")
