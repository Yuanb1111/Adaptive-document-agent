"""Browser notices for terminal analysis and PowerPoint outcomes.

The frameless v2 component runs in the app origin. Its preferences stay in the
browser, so changing them never interrupts a running Streamlit script.
"""

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

OUTCOMES = frozenset({'ready', 'ready_with_warnings', 'export_blocked',
                     'export_failed', 'analysis_failed', 'analysis_interrupted', 'export_interrupted'})


def _event(st, outcome, identity, scope_key):
    if outcome not in OUTCOMES:
        raise ValueError('Unknown notification outcome')
    event_id = sha256(json.dumps([outcome, identity], separators=(',', ':')).encode()).hexdigest()
    attempt = st.session_state.get('analysis_attempts', {}).get(scope_key, {})
    run_id = attempt.get('id')
    export_run = st.session_state.get('ppt_notification_export_runs', {}).get(scope_key)
    if outcome.startswith('export_') or outcome.startswith('ready'):
        if export_run and export_run['analysis_run'] == run_id:
            run_id = f"{run_id or 'cached'}:export:{export_run['id']}"
    return {'mode': 'complete', 'event_id': event_id, 'run_id': run_id, 'outcome': outcome}


def queue_outcome(st, outcome, *, scope_key=None, identity=None):
    """Save trusted, opaque terminal state before any interruptible UI write."""
    scope_key = scope_key or st.session_state.get('analysis_result_key')
    event = _event(st, outcome, identity or scope_key or 'current', scope_key)
    events = st.session_state.setdefault('presentation_notification_outcomes', [])
    if event not in events:
        events.append(event)
        del events[:-20]
    return event


def _emit(event):
    try:
        _component()(data=event, key='presentation_notification_event')
    except Exception:
        # Notification availability must never turn a successful analysis or
        # an already diagnosed export failure into another pipeline failure.
        return


def notify_outcome(st, outcome, *, scope_key=None):
    _emit(queue_outcome(st, outcome, scope_key=scope_key))


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
    """Mount before upload to show browser permission and notification settings."""
    try:
        renderer = _component()
    except ImportError:
        st.caption("Browser notifications require Streamlit 1.53 or newer. Progress remains available on this page.")
        return
    # A stopped Streamlit script cannot mount a component. Replay its saved
    # terminal state when the next script mounts; the browser deduplicates it.
    for scope, attempt in st.session_state.get('analysis_attempts', {}).items():
        if attempt.get('state') in {'failed', 'interrupted'}:
            queue_outcome(st, 'analysis_interrupted' if attempt['state'] == 'interrupted'
                          else 'analysis_failed', scope_key=scope)
    renderer(data={"mode": "settings", 'events': st.session_state.get(
        'presentation_notification_outcomes', [])}, key="presentation_notification_settings")


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


def notify_export_ready(st, verified, *, needs_review=False) -> None:
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
    event = queue_outcome(st, 'ready_with_warnings' if needs_review else 'ready', identity=identity)
    _emit(event)
