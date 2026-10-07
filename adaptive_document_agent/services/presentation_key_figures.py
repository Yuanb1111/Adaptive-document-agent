"""A compact numeric overview drawn from the model-selected analysis charts."""

from __future__ import annotations

from dataclasses import dataclass

from adaptive_document_agent.document_model import period_sort_key
from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric, format_metric_display_value,
)
from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
from adaptive_document_agent.document_model.series import metric_identity_key
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.validation.claim_validator import are_observations_compatible
from .presentation_labels import qualified_metric_name


@dataclass(frozen=True)
class KeyFigure:
    label: str
    value: str
    period: str
    comparison: str
    topic: str
    pages: tuple[int, ...]
    observation_ids: tuple[str, ...]
    prior_period: str = ""


def _figure(chart, observations, topic: str) -> KeyFigure | None:
    from .composition_data import uses_composition_data

    if uses_composition_data(chart):
        return None
    items = [observations[identifier] for identifier in chart.observation_ids
             if identifier in observations]
    items = [item for item in items if item.value is not None and item.period
             and item.evidence and item.validation_status == 'valid' and not item.anomaly_notes]
    if len(items) < 2 or len({metric_identity_key(item) for item in items}) != 1:
        return None
    by_period = {}
    for item in items:
        peers = by_period.setdefault(item.period, [])
        peers.append(item)
    if len(by_period) < 2 or any(len({(o.value, o.raw_value) for o in peers}) != 1
                                 for peers in by_period.values()):
        return None
    ordered = sorted((max(peers, key=lambda item: item.confidence) for peers in by_period.values()),
                     key=lambda item: period_sort_key(item.period))
    earlier, latest = ordered[-2:]
    if not are_observations_compatible(earlier, latest)[0]:
        return None

    def display(item):
        semantic = classify_metric(item.metric_original, unit=item.unit,
                                   raw_unit=item.raw_unit, value=item.value)
        return format_metric_display_value(item.raw_value, item.value, semantic,
                                           raw_unit=item.raw_unit, currency=item.currency, compact=True)

    semantic = classify_metric(latest.metric_original, unit=latest.unit,
                               raw_unit=latest.raw_unit, value=latest.value)
    prior_period = format_observation_period(earlier)
    if semantic.is_percentage:
        movement = float(latest.value) - float(earlier.value)
        comparison = f'{movement:+.1f} pp vs {prior_period}; prior {display(earlier)}'
    elif float(earlier.value) > 0 and float(latest.value) >= 0:
        movement = (float(latest.value) / float(earlier.value) - 1) * 100
        comparison = f'{movement:+.1f}% vs {prior_period}; prior {display(earlier)}'
    else:
        comparison = f'{display(earlier)} in {prior_period}'
    pages = tuple(sorted({e.page for item in (earlier, latest) for e in item.evidence}))
    return KeyFigure(
        label=qualified_metric_name(latest), value=display(latest),
        period=format_observation_period(latest),
        comparison=comparison,
        topic=topic, pages=pages, observation_ids=(earlier.id, latest.id),
        prior_period=prior_period,
    )


def select_key_figures(result: PipelineResult, charts: list) -> list[KeyFigure]:
    """Use the analysis plan's order; never infer which document topics matter."""
    if result.presentation_plan is None:
        return []
    by_chart = {chart.id: chart for chart in charts}
    observations = {item.id: item for item in result.observations}
    from adaptive_document_agent.validation.topic_period_consistency import _source_row
    selected_chart_ids = {cid for slide in result.presentation_plan.slides if slide.slide_type == 'analysis'
                          for cid in slide.chart_ids}
    selected_views = {}
    for cid in selected_chart_ids:
        chart = by_chart.get(cid)
        if chart:
            group = [observations[oid] for oid in chart.observation_ids if oid in observations]
            row = _source_row(group) if group else None
            if row is not None:
                selected_views.setdefault(row, []).append(chart)
    output, seen = [], set()
    for slide in result.presentation_plan.slides:
        if slide.slide_type != 'analysis':
            continue
        for identifier in slide.chart_ids:
            chart = by_chart.get(identifier)
            if chart is None:
                continue
            figure = _figure(chart, observations, slide.section_title or slide.title)
            if figure is None:
                continue
            row = _source_row([observations[oid] for oid in chart.observation_ids if oid in observations])
            peers = [_figure(view, observations, figure.topic) for view in selected_views.get(row, [])]
            peers = [peer for peer in peers if peer is not None]
            if peers:
                # Keep the model-selected measure; prefer its latest selected,
                # internally comparable view. Never retrieve an unselected row
                # or compare an annual value directly with an interim value.
                figure = max([figure, *peers], key=lambda candidate: period_sort_key(
                    observations[candidate.observation_ids[-1]].period))
            identity = figure.label.casefold(), figure.period, figure.value
            if identity in seen:
                continue
            seen.add(identity)
            output.append(figure)
            break
        if len(output) == 12:
            break
    from .text_capacity import wrap_copy
    # An optional overview must never block the whole export because a source
    # metric name is too long for a card. Keep the complete label or omit it.
    wide = [item for item in output if len(wrap_copy(item.label, 5.2, 15)) <= 2]
    if len(wide) < 4:
        return []
    narrow = [item for item in wide if len(wrap_copy(item.label, 3.25, 15)) <= 2]
    return narrow[:6] if len(narrow) >= 5 else wide[:4]


def render_key_figures(presentation, figures: list[KeyFigure]):
    """Render 4–6 exact figures with periods, prior values and source pages."""
    from .slide_compositor import _base
    from .pptx_export import (
        _panel, _source_footer, _text, FOURIER_BG_CARD, FOURIER_DARK,
        FOURIER_MUTED, FOURIER_PURPLE,
    )
    from .text_capacity import wrap_copy

    if not 4 <= len(figures) <= 6:
        raise ValueError('Key Figures requires four to six supported measures.')
    slide, top = _base(presentation, 'Key Figures', 'Latest selected levels and comparable prior values')
    columns = 2 if len(figures) == 4 else 3
    rows = (len(figures) + columns - 1) // columns
    left, gap_x, gap_y = .55, .25, .24
    total = presentation.slide_width.inches - 1.1
    width = (total - gap_x * (columns - 1)) / columns
    bottom = presentation.slide_height.inches - 1.12
    height = (bottom - top - gap_y * (rows - 1)) / rows
    for offset, figure in enumerate(figures):
        x = left + (offset % columns) * (width + gap_x)
        y = top + (offset // columns) * (height + gap_y)
        _panel(slide, x, y, width, height, fill=FOURIER_BG_CARD)
        label_lines = wrap_copy(figure.label, width - .36, 15)
        if len(label_lines) > 2:
            raise ValueError('Key figure label exceeds readable card capacity.')
        label_h = max(.33, len(label_lines) * .27)
        _text(slide, figure.label, x + .18, y + .17, width - .36, label_h,
              size=15, bold=True, color=FOURIER_DARK).name = 'key_figure:label'
        _text(slide, figure.value, x + .18, y + label_h + .28, width - .36, .48,
              size=25, bold=True, color=FOURIER_PURPLE).name = 'key_figure:value'
        _text(slide, figure.period, x + .18, y + label_h + .83, width - .36, .28,
              size=12, color=FOURIER_DARK).name = 'key_figure:period'
        _text(slide, figure.comparison, x + .18, y + label_h + 1.17,
              width - .36, .54, size=11, color=FOURIER_MUTED).name = 'key_figure:comparison'
    pages = sorted({page for figure in figures for page in figure.pages})
    # A source marker in either displayed period needs the same explanation
    # used on the detailed charts. Stars in metric names are unrelated.
    unaudited = any("*" in figure.period or (
        "*" in figure.prior_period and figure.prior_period in figure.comparison
    ) for figure in figures)
    footer = _source_footer(pages) + (" | * Unaudited" if unaudited else "")
    _text(slide, footer, .55, presentation.slide_height.inches - .82,
          total, .20, size=9, color=FOURIER_MUTED)
    slide.notes_slide.notes_text_frame.text = '\n'.join(
        f'{figure.topic}: {figure.label}; {figure.value} in {figure.period}; '
        f'{figure.comparison}; ids={figure.observation_ids}; pages={figure.pages}'
        for figure in figures
    )
    return slide
