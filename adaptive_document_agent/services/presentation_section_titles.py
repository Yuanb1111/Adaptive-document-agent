"""Keep authored chapter labels separate from long analytical conclusions."""
import re
from adaptive_document_agent.models import Observation
from .presentation_trajectory import _DIRECTION, _REVERSAL


_PERIOD_TOKEN = (r'(?:FY\s*(?:19|20)\d{2}|(?:[1-9]|1[02])M\s*(?:19|20)\d{2}|'
                 r'(?:Q[1-4]|[12]H|H[12])\s*(?:19|20)\d{2}|'
                 r'(?:19|20)\d{2}-\d{2}-\d{2})')
_PERIOD_SUFFIX = re.compile(
    rf'(?P<separator>[,;])\s*(?P<periods>{_PERIOD_TOKEN}'
    rf'(?:\s*(?:to|and|[-–—,;])\s*{_PERIOD_TOKEN})*)\s*$', re.I)


def _period_key(label: str | None) -> tuple[str, str] | None:
    """Read an explicit period label without guessing a missing period basis."""
    text = re.sub(r'\s+', '', label or '').rstrip('*').upper()
    if re.fullmatch(r'(?:19|20)\d{2}-\d{2}-\d{2}', text):
        return 'date', text
    match = re.fullmatch(r'(FY|(?:[1-9]|1[02])M|Q[1-4]|[12]H|H[12])((?:19|20)\d{2})', text)
    return (match[1], match[2]) if match else None


def source_scoped_heading(title: str, observations: list[Observation]) -> str:
    """Drop a neutral trailing period inventory when it excludes shown data.

    This changes a chapter label only, not an analytical claim. The original
    title and complete periods remain in the plan, source records and charts.
    Mixed/unknown bases never become a guessed combined date range.
    """
    continuation = ' (continued)' if title.endswith(' (continued)') else ''
    label = title.removesuffix(continuation) if continuation else title
    suffix = _PERIOD_SUFFIX.search(label)
    if not suffix or _DIRECTION.search(label) or _REVERSAL.search(label) or not observations:
        return title
    explicit = [_period_key(token) for token in re.findall(_PERIOD_TOKEN, suffix['periods'], re.I)]
    shown = {_period_key(item.period) for item in observations}
    supported = bool(shown and None not in shown)
    is_range = len(explicit) == 2 and bool(re.search(
        r'\s+to\s+|[–—]|(?<=\d)-(?=FY|[1-9]M|1[02]M|Q|H|[12]H)', suffix['periods'], re.I))
    if supported and is_range and explicit[0][0] == explicit[1][0]:
        family, start = explicit[0]
        end = explicit[1][1]
        supported = (set(explicit).issubset(shown)
                     and all(kind == family and start <= value <= end for kind, value in shown))
    elif supported:
        supported = shown == set(explicit)
    return title if supported else label[:suffix.start()].rstrip() + continuation


def _slide_observations(result, slide):
    chart_ids = set(slide.chart_ids) | {cid for block in slide.visual_blocks for cid in block.chart_ids}
    ids = {oid for chart in getattr(result, 'charts', []) if chart.id in chart_ids
           for oid in [*chart.observation_ids, *chart.total_observation_ids]}
    ids.update(oid for block in slide.visual_blocks if block.role in {'kpi', 'table'}
               for oid in block.observation_ids)
    return [item for item in getattr(result, 'observations', []) if item.id in ids]


def section_heading(result, slide, *, compact=False):
    topic = next((t for t in (result.presentation_topics.topics if result.presentation_topics else [])
                  if t.id == slide.theme_id), None)
    if topic and topic.title.strip() and not (_DIRECTION.search(topic.title) or _REVERSAL.search(topic.title)):
        title = source_scoped_heading(topic.title.strip(), _slide_observations(result, slide))
        if compact:
            # Move only a literal trailing period inventory out of a cramped
            # title. The renderer preserves the full heading in its subtitle.
            title = re.sub(r'[,;]\s*(?:FY|[1369]M|1[02]M|[12]H|Q[1-4])\s*(?:19|20)\d{2}\b.*$',
                           '', title, flags=re.I).strip()
        return title
    return source_scoped_heading(slide.section_title or slide.title, _slide_observations(result, slide))
