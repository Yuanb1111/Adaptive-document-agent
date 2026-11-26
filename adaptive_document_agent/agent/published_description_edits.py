"""Bind edits to published, proof-owned source descriptions."""
import re

from adaptive_document_agent.services.calendar_claims import bound_period_dates
from adaptive_document_agent.services.source_quotes import normalize_quote
from .reported_source_context import qualified_source_scope, qualified_source_statement
from .retained_page_sources import RetainedPage


def recover_display_prefix(iid, edit, current, published, pages):
    """Remove the exact native scope once, only if the resulting audience text is identical."""
    if iid not in published or not isinstance(edit, dict):
        return False
    descriptions = edit.get('source_context_descriptions')
    if not isinstance(descriptions, dict):
        return False
    fixed = RetainedPage.model_validate(current[iid]['page'])
    changed = False
    for slot, text in descriptions.items():
        if slot not in published[iid] or not isinstance(text, str) or len(text) <= 700:
            continue
        item = fixed.source_context[int(slot.removeprefix('context-'))]
        prefix = f'For {qualified_source_scope(item)}, '
        if not text.startswith(prefix) or not published[iid][slot].startswith(prefix):
            continue
        if any(q.page not in pages or not normalize_quote(q.text)
               or normalize_quote(q.text) not in normalize_quote(pages[q.page].text) for q in item.proof_quotes):
            continue
        body = text[len(prefix):]
        if 10 <= len(body) <= 700 and qualified_source_statement(item.model_copy(update={'description': body})) == text:
            descriptions[slot] = body
            changed = True
    return changed


_DATE = r'\d{4}-\d{2}-\d{2}'
_ATTRIBUTED_CHANGE = re.compile(
    rf'\battributes? (?:the|a) (?:increase|decrease|decline|rise|fall|drop|reduction|growth) '
    rf'from (?P<start>{_DATE}) to (?P<end>{_DATE})\b', re.I)


def unresolved_published_comparisons(edit, page, packet, questions):
    """Check only a quoted, source-bound dated comparison the reviewer already asked to clarify."""
    from .retained_description_sentence_repair import quoted_fragments
    descriptions = getattr(edit, 'source_context_descriptions', {})
    rows = packet['primary_observations']
    metrics = {row.get('metric_original') for row in rows}
    if not descriptions or len(metrics) != 1 or not (metric := next(iter(metrics))):
        return []
    name = metric.casefold()
    periods = {row['period'] for row in rows if row.get('period')}
    main = bound_period_dates(page.message, periods).casefold()
    questions = [q for q in questions if name in q.casefold()]
    errors = []
    for slot, text in descriptions.items():
        displayed = packet['published_source_descriptions'][slot].casefold()
        quoted = [q.casefold().rstrip(' ,;:.') for question in questions for _, q in quoted_fragments(question)]
        quoted = [q for q in quoted if q and q in displayed]
        for clause in re.split(r'[.,;!?]', bound_period_dates(text, periods).casefold()):
            if name in clause:
                continue
            for match in _ATTRIBUTED_CHANGE.finditer(clause):
                start, end = match['start'], match['end']
                if not ({start, end} <= periods and any(end in q for q in quoted)):
                    continue
                owner = rf'(?<!\w){re.escape(name)} (?:rose|fell|increased|decreased|declined|grew|dropped) from {start} to {end}\b'
                if re.search(owner, main):
                    errors.append(f'{slot}: the reviewed explanation "{match[0]}" still omits the '
                        f'comparison metric that the main copy names, "{metric}". Resolve this exact '
                        'clause against the fixed proof. Keep the complete source explanation once in '
                        'its own slot and use message span edits to remove duplicated driver sentences.')
    return errors
