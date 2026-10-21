"""Native navigation to selected chart evidence, without duplicating raw tables."""
import json

from .text_capacity import wrap_copy


def index_entries(result, index):
    """One entry per rendered analytical scope, retaining exact source metadata."""
    plan = result.presentation_plan
    if plan is None:
        return []
    by_id = {s.id: s for s in plan.slides if s.slide_type == 'analysis'}
    charts = {chart.id: chart for chart in result.charts}
    scopes = {}
    scope_titles = {}
    for trace in result.presentation_export_trace:
        selected = by_id.get(trace.get('planned_slide_id'))
        if selected is None:
            continue
        key = selected.theme_id or selected.id
        # Fallback section labels can name only the first panel or category.
        # The source index must name every chart actually bound to this scope.
        titles = list(dict.fromkeys(charts[cid].title for cid in trace.get('chart_ids', [])
                                   if cid in charts and charts[cid].title))
        scope_titles[key] = list(dict.fromkeys([*scope_titles.get(key, []), *titles]))
        topic = (selected.section_title or selected.title) if selected.theme_id else (
            ' and '.join(scope_titles[key]) or selected.title or selected.section_title)
        entry = scopes.setdefault(key, {'topic': topic,
                                       'slides': [], 'source_pages': [], 'observation_ids': []})
        entry['topic'] = topic
        for field in ('slides', 'source_pages', 'observation_ids'):
            values = trace['slide_numbers'] if field == 'slides' else trace[field]
            entry[field] = list(dict.fromkeys([*entry[field], *values]))
    entries = []
    from adaptive_document_agent.document_model import period_sort_key
    for entry in scopes.values():
        observations = [index.get(oid) for oid in entry['observation_ids'] if index.get(oid)]
        unique = lambda values: list(dict.fromkeys(v for v in values if v))
        entries.append({
            **entry,
            'metrics': unique(o.metric_original for o in observations),
            'units': unique(o.raw_unit or o.unit for o in observations),
            'periods': sorted(unique(o.period for o in observations), key=period_sort_key),
            'observation_ids': [o.id for o in observations],
            'observations': [o.model_dump(mode='json') for o in observations],
        })
    return entries


def render_data_index(presentation, result, index):
    """Paginate every selected entry at readable native text sizes; never truncate."""
    from .slide_compositor import _base
    from .pptx_export import _text, _source_footer, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE
    entries = index_entries(result, index)
    width = presentation.slide_width.inches - 1.1
    widths = [width * f for f in (.30, .13, .39, .18)]
    headers = ['Chart / metric', 'Source unit', 'Source period', 'PDF pages']
    rows = []
    for entry in entries:
        # Source labels remain exact in notes; visible titles are the reviewed
        # analytical topic names already used on chart pages.
        values = [entry['topic'], '; '.join(entry['units']) or '—',
                  '; '.join(entry['periods']) or '—', ', '.join(map(str, entry['source_pages'])) or '—']
        heights = [len(wrap_copy(v, w - .16, 12)) * .22 + .12 for v, w in zip(values, widths)]
        rows.append((values, max(.44, max(heights))))
    if not rows:
        rows = [(['No selected quantitative charts', '—', '—', '—'], .44)]
    notes = json.dumps({'data_index': entries,
        'source_records': 'All raw observations and extraction evidence remain in the analysis JSON and data exports.'}, ensure_ascii=False)
    pages = []
    slide, top = _base(presentation, 'Data Index', 'Source references for the chart pages')
    bottom = presentation.slide_height.inches - 1.10

    def heading(slide, y):
        x = .55
        for text, w in zip(headers, widths):
            _text(slide, text, x + .08, y, w - .16, .32, size=12, bold=True, color=FOURIER_PURPLE).name = 'data_index:heading'
            x += w
        return y + .45

    y = heading(slide, top)
    for values, height in rows:
        if height > bottom - top - .45:
            raise ValueError('A source-index entry exceeds readable page capacity; review its planned scope')
        if y + height > bottom:
            slide.notes_slide.notes_text_frame.text = notes
            pages.append(slide)
            slide, top = _base(presentation, 'Data Index (continued)', 'Source references for the chart pages')
            y = heading(slide, top)
        x = .55
        for text, w in zip(values, widths):
            _text(slide, text, x + .08, y, w - .16, height, size=12, color=FOURIER_DARK).name = 'data_index:entry'
            x += w
        y += height + .10
    for page in [*pages, slide]:
        from .presentation_body_budget import DATA_INDEX_TAG
        page.element.cSld.set('name', DATA_INDEX_TAG)
        _text(page, _source_footer(sorted({p for entry in entries for p in entry['source_pages']})), .55,
              presentation.slide_height.inches - .82, width, .20, size=9, color=FOURIER_MUTED)
        page.notes_slide.notes_text_frame.text = notes
    return [*pages, slide]
