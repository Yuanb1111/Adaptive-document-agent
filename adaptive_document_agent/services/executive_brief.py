"""Validate editorial copy against literal page-bound evidence, without calculations."""
import re
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


# Preserve explicit magnitudes and currencies as well as numeric tokens. A
# matching 7.3 is not permission to turn millions into billions or USD into RMB.
_QUANTITY = re.compile(
    r"(?i)(?<![A-Za-z0-9_.])(?P<currency>US\$|HK\$|RMB|CNY|USD|HKD|EUR|GBP|人民币|美元|港元|欧元|\$|€|£|¥|￥)?\s*"
    r"(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>trillion|billion|million|thousand|bn|[mkb](?!\w)|%|percent\b|万亿|亿|万|千)?"
    r"(?P<currency_suffix>美元|港元|欧元|人民币|元)?"
)


def _quantities(text: str) -> set[tuple[str, str, str]]:
    return {((m['currency'] or m['currency_suffix'] or '').casefold(),
             PresentationPlanValidator._normalize_number(m['value']),
             (m['unit'] or '').casefold()) for m in _QUANTITY.finditer(text)}


def restore_percentage_symbols(text: str, quotes: list[str], *, source_percentages=frozenset()) -> str:
    """Restore only an unambiguous, item-bound literal percentage unit."""
    units = {}
    for quote in quotes:
        for currency, value, unit in _quantities(quote):
            units.setdefault(value, set()).add((currency, unit))

    def replace(match):
        value = PresentationPlanValidator._normalize_number(match['value'])
        if (not match['currency'] and not match['currency_suffix'] and not match['unit']
                and units.get(value)
                and (units[value] <= {('', '%'), ('', 'percent')}
                     or value in source_percentages and units[value] <= {('', ''), ('', '%'), ('', 'percent')})
                and not re.match(r"\s*(?:years?\b|units?\b|times?\b|percentage\s+points?\b|pp\b)", text[match.end():], re.I)):
            return match.group(0).rstrip() + '%' + match.group(0)[len(match.group(0).rstrip()):]
        return match.group(0)
    return _QUANTITY.sub(replace, text)


def _quoted_table_percentages(item, result):
    """A bare quoted cell needs a resolved, explicitly percentage source column."""
    from collections import defaultdict
    from decimal import Decimal, InvalidOperation
    pages = {p.page_number: p for p in result.document.pages}
    kinds = defaultdict(set)
    for observation in result.observations:
        if observation.value is None or observation.validation_status != 'valid' or observation.anomaly_notes:
            continue
        key = PresentationPlanValidator._normalize_number(observation.raw_value)
        for evidence in observation.evidence:
            quotes = [q.text for q in item.evidence if q.page == evidence.page]
            if not any(key in {v for _, v, _ in _quantities(quote)} for quote in quotes):
                continue
            kinds[key].add(observation.unit_family if observation.unit_family != 'generic' else observation.unit)
    percentages = set()
    for observation in result.observations:
        if (observation.validation_status != 'valid' or observation.anomaly_notes
                or observation.unit not in {'percent', '%'}):
            continue
        key = PresentationPlanValidator._normalize_number(observation.raw_value)
        if not kinds.get(key) or kinds[key] - {'percentage', 'percent'}:
            continue
        for evidence in observation.evidence:
            if evidence.page not in {q.page for q in item.evidence}:
                continue
            page = pages.get(evidence.page)
            table = next((t for t in page.tables if t.table_id == evidence.table_id), None) if page else None
            row, col = observation.row_id, observation.column_id
            if (table is None or row is None or col is None or not 0 <= row < len(table.rows)
                    or not 0 <= col < len(table.column_types) or table.column_types[col] != 'percentage'
                    or table.rows[row].alignment_status != 'resolved' or col >= len(table.rows[row].cells)):
                continue
            cell = table.rows[row].cells[col]
            try:
                value = Decimal(str(cell).strip().replace(',', '').rstrip('%'))
                raw = Decimal(observation.raw_value.strip().replace(',', '').rstrip('%'))
            except InvalidOperation:
                continue
            if value == raw:
                percentages.add(key)
    return percentages


def validate_executive_brief(brief: ExecutiveBrief, result: PipelineResult, *,
                             excerpts: dict[int, str] | None = None) -> list[str]:
    """Check each item's own quotations and numeric scope, including cached exports.

    Semantic selection and interpretation belong to the model. These checks
    prove literal quote location and numeric support, not semantic entailment.
    """
    pages = excerpts if excerpts is not None else {p.page_number: p.text for p in result.document.pages}
    errors = []
    seen = set()
    all_numbers = set()
    for item in brief.items:
        if not item.label.strip() or not item.text.strip():
            errors.append('Brief labels and text must be nonempty.')
        key = normalized(item.text)
        if key in seen:
            errors.append('Brief repeats a finding.')
        seen.add(key)
        allowed = set()
        quantities = set()
        for quote in item.evidence:
            if not normalized(quote.text) or normalized(quote.text) not in normalized(pages.get(quote.page, '')):
                errors.append(f'{item.label}: quote not found on cited page {quote.page}.')
            allowed.update(PresentationPlanValidator._numbers(quote.text))
            quantities.update(_quantities(quote.text))
        claimed = PresentationPlanValidator._numbers(item.label + ' ' + item.text)
        if claimed - allowed:
            errors.append(f'{item.label}: unsupported numeric claims {sorted(claimed - allowed)}.')
        for currency, value, unit in _quantities(item.label + ' ' + item.text):
            if (currency or unit) and not any(value == v and (not currency or currency == c)
                                              and (not unit or unit == u) for c, v, u in quantities):
                errors.append(f'{item.label}: amount changes a source currency or magnitude.')
        all_numbers.update(allowed)
    if PresentationPlanValidator._numbers(brief.title) - all_numbers:
        errors.append('Brief title contains unsupported numbers.')
    return errors


def brief_items(result: PipelineResult):
    """One rendering adapter keeps web and slide copy identical."""
    from .presentation_brief import BriefItem
    brief = result.executive_brief
    if brief is None:
        return []
    errors = validate_executive_brief(brief, result)
    if errors:
        raise ValueError('Invalid executive brief: ' + '; '.join(errors))
    from .brief_context import preserve_brief_context
    pages = {page.page_number: page.text for page in result.document.pages}
    items = []
    for item in brief.items:
        contextual = preserve_brief_context(item, pages)
        text = restore_percentage_symbols(contextual.text, [q.text for q in contextual.evidence],
                                          source_percentages=_quoted_table_percentages(item, result))
        items.append(BriefItem(item.label, text, sorted({q.page for q in contextual.evidence})))
    return items


def display_brief(result: PipelineResult):
    """Use the editorial brief or evidence-bound facts from selected charts.

    The presentation plan selects topics semantically. This fallback only
    formats the selected, comparable observations when model copy cannot pass
    quotation checks; it never changes the extracted records.
    """
    if result.executive_brief is not None:
        return result.executive_brief.title, brief_items(result)
    from adaptive_document_agent.document_model import DocumentIndex
    from .presentation_brief import BriefItem

    plan = result.presentation_plan
    if plan is None:
        return 'Executive Summary', []
    index = DocumentIndex(result.observations)
    charts = {chart.id: chart for chart in result.charts}
    items = []
    for slide in plan.slides:
        if slide.slide_type != 'analysis':
            continue
        facts = [_brief_fact_for_chart(charts[cid], index) for cid in slide.chart_ids if cid in charts]
        facts = [fact for fact in facts if fact is not None][:3]
        if not facts:
            continue
        pages = sorted({page for fact in facts for page in fact[1]})
        label = slide.section_title or slide.title
        items.append(BriefItem(label, ' '.join(fact[0] for fact in facts), pages))
        if len(items) >= 6:
            break
    return 'Executive Summary', items


def _brief_fact_for_chart(chart, index):
    """Render a selected, comparable series as exact levels and periods."""
    from adaptive_document_agent.document_model import display_metric_name, period_sort_key
    from adaptive_document_agent.document_model.period_semantic_validator import format_canonical_period
    from .composition_data import uses_composition_data
    from .financial_formatter import format_compact_currency
    from .pptx_export import _chart_findings
    from .language_qa import clean_display_copy

    if uses_composition_data(chart) or not _chart_findings([chart], index):
        return None
    unique = {}
    for identifier in chart.observation_ids:
        item = index.get(identifier)
        if item is not None and item.period and item.value is not None:
            previous = unique.get(item.period)
            if previous is None or item.confidence > previous.confidence:
                unique[item.period] = item
    ordered = sorted(unique.values(), key=lambda item: period_sort_key(item.period))
    if len(ordered) < 2:
        return None
    points = [ordered[0], ordered[-1]]
    if len(ordered) >= 3:
        values = [float(item.value) for item in ordered]
        turning = [i for i in range(1, len(values)-1)
                   if (values[i]-values[i-1]) * (values[i+1]-values[i]) < 0]
        if turning:
            pivot = max(turning, key=lambda i: abs(values[i] - (
                values[0] + (values[-1]-values[0])*i/(len(values)-1))))
            points.insert(1, ordered[pivot])

    def value(item):
        number = float(item.value)
        if item.currency:
            shown = format_compact_currency(number, raw_unit=item.raw_unit,
                                            currency=item.currency, is_base_value=True)
            return shown.replace('-'+item.currency, item.currency+' -', 1)
        if item.unit in {'percent', '%'} or item.raw_unit == '%':
            return f'{number:,.1f}%'
        if item.unit in {'count', 'units'}:
            return f'{number:,.0f} units'
        return f'{number:,.1f} {item.unit or item.raw_unit or ""}'.strip()

    label = clean_display_copy(display_metric_name(ordered[0]))
    levels = '; '.join(f'{format_canonical_period(item)} {value(item)}' for item in points)
    pages = sorted({e.page for item in points for e in item.evidence})
    return f'{label}: {levels}.', pages
