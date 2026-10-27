"""Literal amount-row reading aids; no inferred labels or assurance decisions."""
import re
from typing import TYPE_CHECKING

from adaptive_document_agent.services.source_quotes import normalize_quote

if TYPE_CHECKING:
    from .report_audit_scope import AuditMeasureBinding


VALUE_QUOTE_INSTRUCTIONS = (
    'source_metric is an editable proposed counterpart label, not required source wording. '
    'Copy the literal label of the SAME measure from the covered source row; it may differ '
    'from the target label only when full source context supports that identity. Never insert '
    'a target/summary label into a blank-label subtotal row or combine text from different '
    'pages. An unlabeled subtotal, matching amount, or collection of component rows cannot '
    'satisfy this literal labeled-row binding contract. Search the other supplied pages for '
    'a complete labeled counterpart; if none supports the exact measure and signed amount, '
    'retain that observation as unresolved with a source-specific reason for independent '
    'review. Do not invent an amount row by adding components. value_reading_windows are '
    'literal text-location aids on the previously proposed page, not approved counterparts '
    'or proof that no counterpart exists elsewhere. A neighboring label does not name an '
    'unlabeled row. Inspect the full pages to establish row and column ownership. ')


def value_reading_windows(context: dict, binding: 'AuditMeasureBinding') -> dict:
    """Locate the proposed signed spelling without selecting a semantic counterpart."""
    source = next((p for p in context['source_pages'] if p['page'] == binding.value_quote.page), None)
    windows, omitted = [], 0
    text = source['text'] if source else ''
    # Exact spelling and numeric boundaries prevent a positive token from
    # locating a negative amount, a larger number or a different decimal.
    raw = binding.source_raw_value.strip()
    token = re.compile(r'(?<![\w.,()+\-−])' + re.escape(raw) + r'(?![\w,()]|\.\d)') if raw else None
    lines = [line for line in re.finditer(r'[^\r\n]+', text) if line[0].strip()]
    for index, line in enumerate(lines):
        if token is None or not token.search(line[0]):
            continue
        start = lines[max(0, index - 2)].start()
        end = lines[min(len(lines) - 1, index + 2)].end()
        if end - start > 1800 or len(windows) >= 4:
            omitted += 1
            continue
        windows.append(dict(page=binding.value_quote.page, start_char=start, end_char=end,
                            text=text[start:end], amount_line=line[0]))
    return dict(proposed_page=binding.value_quote.page, proposed_page_available=source is not None,
                proposed_metric=binding.source_metric, proposed_raw_value=binding.source_raw_value,
                metric_literal_on_proposed_page=bool(normalize_quote(binding.source_metric))
                    and normalize_quote(binding.source_metric) in normalize_quote(text),
                windows=windows, omitted_windows=omitted, full_source_pages_retained=True,
                semantic_correspondence_established=False, assurance_established=False)
