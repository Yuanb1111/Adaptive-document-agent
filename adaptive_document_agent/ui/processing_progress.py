"""Stage-based progress: real completion events, with no time-driven animation."""

from html import escape
import re
from time import monotonic

from .branding import PURPLE


# These are workflow weights, not a prediction of remaining time. A model
# request can stay at one milestone for as long as it actually takes.
MILESTONES = {
    "Reading PDF": 1,
    "Understanding document": 4,
    "Mapping the large document and selecting relevant sections": 6,
    "Merging selected sections into the global document profile": 45,
    "Extracting tables from selected sections": 52,
    "Extracting structured observations": 58,
    "Normalizing financial data layer": 64,
    "Building document model": 65,
    "Generating analysis candidates": 66,
    "Selecting useful analyses": 70,
    "Reusing extracted evidence for selected analyses": 71,
    "Running deterministic calculations": 72,
    "Checking consistency and validating results": 73,
    "Generating insights and dynamic report": 75,
    "Selecting presentation questions before chart generation": 80,
    "Planning report outline": 80,
    "Planning report outline and selecting presentation questions": 80,
    "Generating charts from selected presentation questions": 83,
    "Planning presentation narrative": 85,
    "Complete": 90,
    "Preparing complete display text for translation": 90,
    "Verifying requested report coverage": 90,
    "Checking PowerPoint evidence": 91,
    "Building PowerPoint": 94,
    "Rendering and checking PowerPoint layout": 97,
}


class ProcessingProgress:
    def __init__(self, placeholder, timer=None, *, clock=monotonic):
        self.placeholder = placeholder
        self.timer = timer
        self.timer_sequence = 0
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.percent = 0
        self.label = "Waiting to start"
        self.state = "running"
        self.started_at = self.stage_started_at = self.clock()
        self.stopped_at = None
        self.render()

    def update(self, stage: str) -> None:
        target = MILESTONES.get(stage, self.percent)
        chunk = re.search(r"^(Understood|Understanding) selected pages .*\((\d+)/(\d+)\)$", stage)
        if chunk:
            finished, total = int(chunk[2]), int(chunk[3])
            if chunk[1] == "Understanding":
                finished -= 1  # Sequential discovery announces a request before it runs.
            if total > 0:
                target = 10 + int(35 * max(0, min(finished, total)) / total)
        elif stage.startswith("Understanding selected sections with"):
            target = 10
        scoring = re.fullmatch(r'Scoring analysis candidates \((\d+)/(\d+)\)', stage)
        if scoring and int(scoring[2]) > 0:
            target = 66 + int(3 * min(int(scoring[1]), int(scoring[2])) / int(scoring[2]))
        self.percent = min(99, max(self.percent, target))
        label = "Analysis complete; preparing PowerPoint" if stage == "Complete" else stage
        if label != self.label:
            self.stage_started_at = self.clock()
        self.label = label
        self.state = "running"
        self.stopped_at = None
        self.render()

    def finish(self) -> None:
        """Called only after verified export returns a downloadable presentation."""
        self.percent = 100
        self.label = "PowerPoint ready to download"
        self.state = "complete"
        self.stopped_at = self.clock()
        self.render()

    def fail(self, label: str) -> None:
        self.state = "error"
        self.label = label
        self.stopped_at = self.clock()
        self.render()

    def snapshot(self) -> dict:
        """Plain metadata only; safe to transfer from a worker to the UI."""
        return {key: getattr(self, key) for key in (
            'percent', 'label', 'state', 'started_at', 'stage_started_at', 'stopped_at')}

    def restore(self, snapshot: dict) -> None:
        for key, value in snapshot.items():
            setattr(self, key, value)
        self.render()

    def clear(self) -> None:
        self.placeholder.empty()
        if self.timer is not None:
            self.timer.empty()

    def mount(self, st) -> None:
        """Fragment widgets must live in placeholders created in that fragment."""
        self.placeholder = st.empty()
        self.timer = st.empty()

    def render(self) -> None:
        if self.placeholder is None:
            return
        color = {"running": PURPLE, "complete": "#15803D", "error": "#B91C1C"}[self.state]
        note = ("Completed" if self.state == "complete" else
                "Stopped at this stage; see details below." if self.state == "error" else
                "Estimated workflow progress, not a remaining-time estimate.")
        running = ('<span class="fourier-running" aria-hidden="true"></span> Running'
                   if self.state == 'running' else 'Completed' if self.state == 'complete' else 'Stopped')
        self.placeholder.markdown(
            '<style>@keyframes fourier-spin{to{transform:rotate(360deg)}}'
            '.fourier-running{display:inline-block;width:12px;height:12px;margin-right:5px;'
            'border:2px solid #ccc;border-top-color:#7A24FD;border-radius:50%;'
            'animation:fourier-spin 1s linear infinite;vertical-align:middle;}'
            '@media(prefers-reduced-motion:reduce){.fourier-running{animation:none}}</style>'
            f'<div class="fourier-progress">'
            f'<div role="progressbar" aria-label="Document to PowerPoint progress" '
            f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{self.percent}" '
            f'aria-valuetext="{self.percent}%: {escape(self.label, quote=True)}" '
            'style="position:relative;width:84px;height:84px;flex-shrink:0;">'
            f'<div style="position:absolute;inset:0;border-radius:50%;background:conic-gradient('
            f'{color} {self.percent}%,rgba(128,128,128,.18) 0);'
            'mask:radial-gradient(farthest-side,transparent calc(100% - 7px),#000 0);'
            '-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 7px),#000 0);"></div>'
            f'<span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
            f'font-size:21px;font-weight:650;">{self.percent}%</span></div>'
            f'<div><div style="font-weight:600;">{escape(self.label)}</div>'
            f'<div role="status" style="font-size:13px;margin-top:5px;">{running}</div>'
            f'<div style="font-size:13px;opacity:.7;margin-top:5px;">{note}</div></div></div>',
            unsafe_allow_html=True,
        )
        if self.timer is not None:
            from .progress_timer import render
            now = self.stopped_at if self.stopped_at is not None else self.clock()
            self.timer_sequence += 1
            render(self.timer, {
                'elapsed': max(0, now - self.started_at),
                'stage_elapsed': max(0, now - self.stage_started_at),
                'running': self.state == 'running',
            }, key=f'analysis_elapsed_timer_{self.timer_sequence}')
