"""Browser elapsed-time clock; it never advances workflow completion."""

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _sources():
    assets = Path(__file__).with_name('assets')
    return {kind: (assets / f'progress_timer.{suffix}').read_text(encoding='utf-8')
            for kind, suffix in (('html', 'html'), ('css', 'css'), ('js', 'mjs'))}


def render(placeholder, data, *, key):
    from streamlit.components.v2 import component
    with placeholder.container():
        component('analysis_elapsed_timer', **_sources())(
            data=data, key=key, height=48)
