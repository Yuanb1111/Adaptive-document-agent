"""Keep authored chapter labels separate from long analytical conclusions."""
import re
from .presentation_trajectory import _DIRECTION, _REVERSAL


def section_heading(result, slide, *, compact=False):
    topic = next((t for t in (result.presentation_topics.topics if result.presentation_topics else [])
                  if t.id == slide.theme_id), None)
    if topic and topic.title.strip() and not (_DIRECTION.search(topic.title) or _REVERSAL.search(topic.title)):
        title = topic.title.strip()
        if compact:
            # Move only a literal trailing period inventory out of a cramped
            # title. The renderer preserves the full heading in its subtitle.
            title = re.sub(r'[,;]\s*(?:FY|[1369]M|1[02]M|[12]H|Q[1-4])\s*(?:19|20)\d{2}\b.*$',
                           '', title, flags=re.I).strip()
        return title
    return slide.section_title or slide.title
