"""Literal reading windows for a failed header quote; never assurance decisions."""
import re


HEADER_QUOTE_INSTRUCTIONS = (
    'For header_quote and covered_header_quote, copy one continuous source passage containing '
    'BOTH the reporting duration/date tiers AND the complete year row. Preserve intervening '
    'text, adjacent column headings and line breaks, including headings for other periods. '
    'Do not join separated header fragments or repair a nonliteral quote by deleting its year. '
    'header_reading_windows are bounded literal reading aids on previously proposed pages, '
    'not approved headers or proof of column ownership or assurance. Inspect the full source '
    'page and independently select the exact header belonging to the mapped amount. ')


def header_reading_windows(context: dict, binding, period: str | None) -> dict:
    """Return exact line windows around year tokens on model-proposed pages.

    Python locates text only. It neither associates a year with a column nor
    chooses an assurance status, and never changes the proposed binding.
    Full source pages remain available when these bounded aids are insufficient.
    """
    year = re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', period or '')
    page_ids = {binding.header_quote.page, binding.value_quote.page}
    windows = []
    omitted = 0
    if year:
        token = re.compile(r'(?<!\d)' + year[0] + r'(?!\d)')
        for source in context['source_pages']:
            if source['page'] not in page_ids:
                continue
            text = source['text']
            lines = list(re.finditer(r'[^\r\n]+', text))
            lines = [line for line in lines if line[0].strip()]
            seen = set()
            for index, line in enumerate(lines):
                if not token.search(line[0]):
                    continue
                start = lines[max(0, index - 4)].start()
                end = lines[min(len(lines) - 1, index + 2)].end()
                if (start, end) in seen:
                    continue
                seen.add((start, end))
                # Never clip a row or stitch disjoint fragments to fit a quote.
                if end - start > 1800 or len(windows) >= 4:
                    omitted += 1
                    continue
                windows.append(dict(page=source['page'], start_char=start,
                                    end_char=end, text=text[start:end]))
    return dict(required_period=period, proposed_pages=sorted(page_ids),
                windows=windows, omitted_windows=omitted,
                full_source_pages_retained=True, assurance_established=False)
