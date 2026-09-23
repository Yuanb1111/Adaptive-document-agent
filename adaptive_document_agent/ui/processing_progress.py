"""Stage-based progress: real completion events, with no time-driven animation."""

from html import escape
import re


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
    "Planning presentation narrative": 85,
    "Complete": 90,
    "Checking PowerPoint evidence": 91,
    "Building PowerPoint": 94,
    "Rendering and checking PowerPoint layout": 97,
}


class ProcessingProgress:
    def __init__(self, placeholder):
        self.placeholder = placeholder
        self.reset()

    def reset(self) -> None:
        self.percent = 0
        self.label = "Waiting to start"
        self.state = "running"
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
        self.percent = min(99, max(self.percent, target))
        self.label = "Analysis complete; preparing PowerPoint" if stage == "Complete" else stage
        self.state = "running"
        self.render()

    def finish(self) -> None:
        """Called only after verified export returns a downloadable presentation."""
        self.percent = 100
        self.label = "PowerPoint ready to download"
        self.state = "complete"
        self.render()

    def fail(self, label: str) -> None:
        self.state = "error"
        self.label = label
        self.render()

    def render(self) -> None:
        color = {"running": "#6D28D9", "complete": "#15803D", "error": "#B91C1C"}[self.state]
        note = ("Completed" if self.state == "complete" else
                "Stopped at this stage; see details below." if self.state == "error" else
                "Estimated workflow progress, not a remaining-time estimate.")
        self.placeholder.markdown(
            f'<div style="display:flex;align-items:center;gap:20px;margin:12px 0 22px;">'
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
            f'<div style="font-size:13px;opacity:.7;margin-top:5px;">{note}</div></div></div>',
            unsafe_allow_html=True,
        )
