"""Validate editorial copy against literal page-bound evidence, without calculations."""
import re
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from .source_quotes import normalize_quote, continuous_quote_passages


def normalized(text: str) -> str:
    return normalize_quote(text)


_UNIT_ONLY_LABEL = re.compile(
    r"(?ix)^\s*(?:in\s+)?(?:RMB|CNY|CNH|USD|HKD|SGD|GBP|EUR|JPY|AUD|CAD|CHF|US\$|HK\$|[$€£¥￥])?\s*"
    r"(?:in\s+)?(?:trillions?|billions?|millions?|thousands?|bn|mn|[mkb]|['’]000s?)"
    r"(?:\s*(?:per|/)\s*\w+)?\s*$"
)


# Preserve explicit magnitudes and currencies as well as numeric tokens. A
# matching 7.3 is not permission to turn millions into billions or USD into RMB.
_QUANTITY = re.compile(
    r"(?i)(?<![A-Za-z0-9_.])(?P<currency>US\$|HK\$|RMB|CNY|USD|HKD|EUR|GBP|人民币|美元|港元|欧元|\$|€|£|¥|￥)?\s*"
    r"(?P<value>(?>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?))\s*"
    r"(?P<unit>trillion|billion|million|thousand|bn|mn|[mkb]|%|percent\b|万亿|十亿|百万|亿|万|千)?"
    r"(?P<currency_suffix>美元|港元|欧元|人民币|元)?(?![A-Za-z0-9_])"
)

_MONEY_QUANTITY = re.compile(
    r"(?ix)(?<![A-Za-z0-9_.])"
    r"(?:(?P<prefix>US\$|HK\$|RMB|CNY|CNH|USD|HKD|SGD|GBP|EUR|JPY|AUD|CAD|CHF|人民币|美元|港元|欧元|[$€£¥￥])\s*)?"
    r"(?P<open>\()?\s*(?P<sign>[+\-\u2212])?\s*"
    r"(?P<value>(?>\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(?P<unit>trillion\b|billion\b|million\b|thousand\b|bn\b|mn\b|[mkb]\b|万亿|十亿|百万|亿|万|千)(?:元)?\s*(?(open)\))\s*"
    r"(?P<suffix>US\$|HK\$|RMB|CNY|CNH|USD|HKD|SGD|GBP|EUR|JPY|AUD|CAD|CHF|人民币|美元|港元|欧元|[$€£¥￥])?"
    r"(?![A-Za-z0-9_])"
)


def _quantities(text: str) -> set[tuple[str, str, str]]:
    text = PresentationPlanValidator._without_period_durations(text)
    text = PresentationPlanValidator._canonicalize_money_signs(text)
    money_matches = list(_MONEY_QUANTITY.finditer(text))
    money_spans = [match.span() for match in money_matches]
    output = {((match['currency'] or match['currency_suffix'] or '').casefold(),
               PresentationPlanValidator._normalize_number(match['value']),
               (match['unit'] or '').casefold()) for match in _QUANTITY.finditer(text)
              if not any(start <= match.start() and match.end() <= end for start, end in money_spans)}
    for match in money_matches:
        value = PresentationPlanValidator._normalize_number(match['value'])
        if match['sign'] in {'-', '−'} or match['open']:
            value = '-' + value.lstrip('-')
        output.add(((match['prefix'] or match['suffix'] or '').casefold(), value,
                    match['unit'].casefold()))
    return output


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


def _quoted_table_percentages(item, result, *, quotations=None):
    """A bare quoted cell needs a resolved, explicitly percentage source column."""
    from collections import defaultdict
    from decimal import Decimal, InvalidOperation
    pages = {p.page_number: p for p in result.document.pages}
    # Request-scoped memoization: no document content survives this validation.
    parsed = {}
    def quantities(text):
        text = str(text)
        if text not in parsed:
            parsed[text] = _quantities(text)
        return parsed[text]
    kinds = defaultdict(set)
    bound_cells = set()
    quoted_passages = quotations if quotations is not None else item.evidence
    quotes_by_page = defaultdict(list)
    for quote in quoted_passages:
        quotes_by_page[quote.page].append(quote.text)
    for observation in result.observations:
        if observation.value is None or observation.validation_status != 'valid' or observation.anomaly_notes:
            continue
        key = PresentationPlanValidator._normalize_number(observation.raw_value)
        for evidence in observation.evidence:
            quotes = quotes_by_page.get(evidence.page, [])
            if not quotes:
                continue
            value_quotes = [quote for quote in quotes if key in {v for _, v, _ in quantities(quote)}]
            if value_quotes:
                # A same-page/same-value observation with another unit keeps
                # the value ambiguous even when it has no resolved table cell.
                kinds[key].add(observation.unit_family if observation.unit_family != 'generic' else observation.unit)
            page = pages.get(evidence.page)
            table = next((t for t in page.tables if t.table_id == evidence.table_id), None) if page else None
            row, col = observation.row_id, observation.column_id
            if (table is None or row is None or col is None or not 0 <= row < len(table.rows)
                    or not 0 <= col < len(table.column_types) or col >= len(table.rows[row].cells)):
                continue
            labels = [evidence.row_label, observation.metric_original, observation.metric_canonical]
            labels.extend(cell for index, cell in enumerate(table.rows[row].cells)
                          if index != col and cell and not quantities(cell))
            normalized_labels = {normalized(str(label)) for label in labels if label and len(normalized(str(label))) >= 3}
            matching_quotes = [quote for quote in value_quotes
                               if any(label in normalized(quote) for label in normalized_labels)
                               and _quote_selects_cell(quote, key, evidence.page, table.table_id, row, col, page, quantities=quantities)]
            if not matching_quotes:
                continue
            bound_cells.add((observation.id, evidence.page, evidence.table_id, row, col))
    percentages = set()
    for observation in result.observations:
        if (observation.validation_status != 'valid' or observation.anomaly_notes
                or observation.unit not in {'percent', '%'}):
            continue
        key = PresentationPlanValidator._normalize_number(observation.raw_value)
        if not kinds.get(key) or kinds[key] - {'percentage', 'percent'}:
            continue
        for evidence in observation.evidence:
            if (observation.id, evidence.page, evidence.table_id,
                    observation.row_id, observation.column_id) not in bound_cells:
                continue
            if evidence.page not in {q.page for q in quoted_passages}:
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


def _quote_selects_cell(quote, key, page_number, table_id, row_id, column_id, page, *, quantities=None) -> bool:
    """Require a quote to select one exact same-valued cell on its page."""
    from decimal import Decimal, InvalidOperation

    quantities = quantities or _quantities

    def numbers(cell):
        values = set()
        for _, value, _ in quantities(str(cell)):
            try:
                values.add(Decimal(value))
            except InvalidOperation:
                continue
        return values

    try:
        wanted = Decimal(key)
    except InvalidOperation:
        return False
    quote_text = normalized(quote)
    quote_terms = " ".join(re.sub(r"[^a-z0-9]+", " ", quote.casefold()).split())

    def descriptor_matches(value) -> bool:
        if not value:
            return False
        literal = normalized(str(value))
        terms = " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())
        return literal in quote_text or bool(terms and terms in quote_terms)

    candidates = []
    for table in page.tables:
        for row_index, row in enumerate(table.rows):
            row_labels = [normalized(str(cell)) for cell in row.cells
                          if cell and not numbers(cell) and len(normalized(str(cell))) >= 3]
            if row_labels and not any(label in quote_text for label in row_labels):
                continue
            for column_index, cell in enumerate(row.cells):
                if wanted not in numbers(cell):
                    continue
                descriptors = []
                if column_index < len(table.headers):
                    descriptors.append(table.headers[column_index])
                if column_index < len(table.column_periods):
                    descriptors.append(table.column_periods[column_index])
                descriptors.extend((table.table_title, table.context_label))
                score = sum(descriptor_matches(value) for value in descriptors)
                candidates.append((score, table.table_id, row_index, column_index))
    target = (table_id, row_id, column_id)
    if not candidates:
        return False
    if len(candidates) == 1:
        return candidates[0][1:] == target
    best = max(score for score, *_ in candidates)
    selected = [candidate[1:] for candidate in candidates if candidate[0] == best]
    return best > 0 and selected == [target]


def validate_executive_brief(brief: ExecutiveBrief, result: PipelineResult, *,
                             excerpts: dict[int, str] | None = None) -> list[str]:
    """Check each item's own quotations and numeric scope, including cached exports.

    Semantic selection and interpretation belong to the model. These checks
    prove literal quote location and numeric support, not semantic entailment.
    """
    pages = excerpts if excerpts is not None else {p.page_number: p.text for p in result.document.pages}
    original_pages = {p.page_number: p.text for p in result.document.pages}
    errors = []
    seen = set()
    all_numbers = set()
    for item in brief.items:
        if item.comparison_table:
            from .brief_table_units import literal_table_units
            item = item.model_copy(update={'comparison_table': literal_table_units(item, original_pages)})
        passages = continuous_quote_passages(item.evidence, original_pages)
        if not item.label.strip() or not item.text.strip():
            errors.append('Brief labels and text must be nonempty.')
        elif _UNIT_ONLY_LABEL.fullmatch(item.label):
            errors.append(f'{item.label}: label is a unit header, not a finding or metric name.')
        from adaptive_document_agent.models.executive_brief import brief_claim_text
        key = normalized(brief_claim_text(item, include_label=False))
        if key in seen:
            errors.append('Brief repeats a finding.')
        seen.add(key)
        if item.comparison_table:
            # A table's semantic organisation belongs to the model. Its cells
            # must remain literal item-bound source passages, including units
            # and assumptions, rather than reformulated or calculated values.
            for row in item.comparison_table.rows:
                for cell in row:
                    if not any(normalized(cell) in normalized(q.text) for q in passages):
                        errors.append(f'{item.label}: comparison table cell lacks literal item-bound evidence.')
            from .brief_context import _CONDITION, _outcomes
            shown = _outcomes(brief_claim_text(item))
            for passage in passages:
                if len(_CONDITION.findall(passage.text)) < 2:
                    continue
                if any(not values <= shown.get(unit, set()) for unit, values in _outcomes(passage.text).items()):
                    missing = {unit: sorted(values - shown.get(unit, set()))
                                   for unit, values in _outcomes(passage.text).items()
                                   if values - shown.get(unit, set())}
                    errors.append(f'{item.label}: comparison table omits a quoted conditional outcome or its unit: {missing}.')
        allowed = set()
        quantities = set()
        for quote in item.evidence:
            if (not normalized(quote.text)
                    or normalized(quote.text) not in normalized(pages.get(quote.page, ''))
                    or normalized(quote.text) not in normalized(original_pages.get(quote.page, ''))):
                errors.append(f'{item.label}: quote not found on cited page {quote.page}.')
        for passage in passages:
            allowed.update(PresentationPlanValidator._numbers(passage.text))
            # A following percentage-header line must not turn the final year
            # in an explicitly quoted year row into a percentage token.
            for line in passage.text.splitlines():
                if re.fullmatch(r'\s*(?:(?:19|20)\d{2}\s+)+(?:19|20)\d{2}\s*', line):
                    allowed.update(PresentationPlanValidator._numbers(line))
            quantities.update(_quantities(passage.text))
        source_percentages = _quoted_table_percentages(item, result, quotations=passages)
        from .brief_table_evidence import quoted_table_context, canonical_quantity
        table_context = quoted_table_context(item, result, excerpts=excerpts)
        source_percentages.update(table_context.percentages)
        # Accounting parentheses in a complete source row are signs, never
        # authorization to publish a positive amount with the same digits.
        allowed.difference_update(table_context.misparsed_positive_numbers)
        allowed.update(table_context.signed_numbers)
        quantities = {q for q in quantities if q[1] not in table_context.misparsed_positive_numbers}
        quantities.update(table_context.quantities)
        quantities = {canonical_quantity(*quantity) for quantity in quantities}
        from .brief_quantity_representation import magnitude_claim_text
        claim_text, representation_errors = magnitude_claim_text(item, table_context, quantities)
        errors.extend(f'{item.label}: {error}.' for error in representation_errors)
        errors.extend(f'{item.label}: {error}.' for error in table_context.basis_errors(claim_text))
        # The deterministic table model supplies a unit that a body-cell quote
        # cannot repeat.  Add only the exact resolved values, not every number
        # from a percentage-bearing page.
        allowed.update(value + '%' for value in source_percentages)
        claimed = PresentationPlanValidator._numbers(table_context.numeric_claim_text(claim_text))
        if claimed - allowed:
            errors.append(f'{item.label}: unsupported numeric claims {sorted(claimed - allowed)}.')
        for currency, value, unit in _quantities(claim_text):
            currency, value, unit = canonical_quantity(currency, value, unit)
            # A PDF table often stores the percentage sign once in its column
            # header.  The source quote then legitimately contains a bare cell
            # such as 50.5.  Accept the percent suffix only when extraction has
            # resolved this exact cited cell as a percentage column.
            if unit in {'%', 'percent'} and not currency and value in source_percentages:
                continue
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
        from .brief_table_evidence import quoted_table_context
        text = restore_percentage_symbols(contextual.text, [q.text for q in contextual.evidence],
                                          source_percentages=(_quoted_table_percentages(item, result)
                                                              | quoted_table_context(item, result).percentages))
        from .brief_money_display import readable_money
        text = readable_money(text)
        from .brief_table_units import literal_table_units
        items.append(BriefItem(item.label, text, sorted({q.page for q in contextual.evidence}),
                               table=literal_table_units(item, pages), conditions=contextual.conditions))
    return items


def display_brief(result: PipelineResult):
    """Use the editorial brief or facts from the model-selected evidence.

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
    topics = {}
    for slide in plan.slides:
        if slide.slide_type != 'analysis':
            continue
        label = slide.section_title or slide.title
        key = slide.section_id or normalized(label)
        if key not in topics:
            topics[key] = (label, {})
        selected = [charts[cid] for cid in slide.chart_ids if cid in charts]
        selected.extend(_selected_table_series(slide, index, result))
        for chart in selected:
            fact = _brief_fact_for_chart(chart, index)
            if fact is not None:
                signature = _brief_chart_signature(chart, index)
                retained = topics[key][1].setdefault(signature,
                    {"chart": chart, "text": fact[0], "pages": set()})
                retained["pages"].update(fact[1])
    from .brief_source_deduplication import deduplicate_brief_facts
    from .presentation_labels import compact_section_heading
    for label, facts in topics.values():
        facts = {i: fact for i, fact in enumerate(deduplicate_brief_facts(facts.values(), index))}
        if facts:
            # Rounded display copy cannot prove that source facts are equal.
            # When it masks a source difference, show exact levels for every
            # period, including an otherwise omitted intermediate point.
            text_counts = {}
            for fact in facts.values():
                text_counts[fact["text"]] = text_counts.get(fact["text"], 0) + 1
            for fact in facts.values():
                if text_counts[fact["text"]] > 1:
                    exact = _brief_fact_for_chart(fact["chart"], index, exact=True)
                    if exact is not None:
                        fact["text"] = exact[0]
                        fact["pages"].update(exact[1])
            pages = sorted({page for fact in facts.values() for page in fact["pages"]})
            # One complete measure per paragraph is easier to scan than an
            # undifferentiated inventory. The original periods remain explicit.
            items.append(BriefItem(compact_section_heading(label),
                                   '\n'.join(fact["text"] for fact in facts.values()), pages))
    return 'Executive Summary', items


def _selected_table_series(slide, index, result):
    """Adapt selected table cells to the same comparable-series fact checks.

    Presentation format does not determine summary eligibility. Each series
    still needs valid, page-bound values and a consistent source scope; no
    unrelated observation is retrieved just to fill a summary.
    """
    from collections import defaultdict
    from adaptive_document_agent.models import ChartPlan
    from adaptive_document_agent.document_model.series import metric_identity_key
    from .presentation_evidence import (
        ambiguous_source_table_ids, evidence_groups, observation_uses_ambiguous_table,
    )

    ids = list(slide.observation_ids)
    ids.extend(oid for block in slide.visual_blocks for oid in block.observation_ids)
    ambiguous = ambiguous_source_table_ids(result)
    scopes = defaultdict(list)
    for identifier in dict.fromkeys(ids):
        item = index.get(identifier)
        if (item is None or item.value is None or not item.evidence
                or item.validation_status != 'valid' or item.anomaly_notes
                or observation_uses_ambiguous_table(item, ambiguous)):
            continue
        scopes[(metric_identity_key(item), item.parent_section)].append(item)
    series = []
    for scope in scopes.values():
        for group in evidence_groups(scope):
            # Conflicting observations stay in the data, never silently choose
            # the more confident cell as a summary endpoint.
            values = defaultdict(set)
            for item in group:
                values[item.period].add(item.value)
            if any(len(points) > 1 for points in values.values()):
                continue
            series.append(ChartPlan(id=f'brief-table-{len(series)}', title=slide.title,
                chart_type='table', question=slide.message or slide.title,
                observation_ids=[item.id for item in group]))
    return series


def _brief_chart_signature(chart, index):
    """Compare complete fact scope and source precision, not rounded prose."""
    from adaptive_document_agent.document_model.series import metric_identity_key
    return frozenset((metric_identity_key(item), item.metric_original, item.metric_canonical,
        item.parent_section, item.unit, item.raw_unit, item.unit_scale, item.raw_value, item.value,
        item.period, item.period_basis, item.period_type, item.period_start, item.period_end,
        item.as_of_date, item.audited_status, item.fact_type)
        for identifier in chart.observation_ids if (item := index.get(identifier)) is not None)


def _brief_exact_number(number):
    """Decimal spelling of a normalized number, without binary float tails."""
    from decimal import Decimal
    shown = format(Decimal(str(number)), ",f")
    return shown.rstrip('0').rstrip('.') if '.' in shown else shown


def _brief_fact_for_chart(chart, index, *, exact=False):
    """Render a selected, comparable series as exact levels and periods."""
    from adaptive_document_agent.document_model import period_sort_key
    from .presentation_labels import qualified_metric_name
    from adaptive_document_agent.document_model.period_semantic_validator import format_canonical_period
    from .composition_data import uses_composition_data
    from .financial_formatter import format_compact_currency, split_unit_basis
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
    points = ordered if exact else [ordered[0], ordered[-1]]
    if len(ordered) >= 3 and not exact:
        values = [float(item.value) for item in ordered]
        turning = [i for i in range(1, len(values)-1)
                   if (values[i]-values[i-1]) * (values[i+1]-values[i]) < 0]
        if turning:
            pivot = turning[-1]
            points.insert(1, ordered[pivot])

    def value(item):
        number = float(item.value)
        if item.currency:
            _, basis = split_unit_basis(item.raw_unit)
            if basis:
                # Prices/rates need their reported differences visible. Do not
                # round all small per-unit values to the same integer thousand.
                return f'{item.currency} {_brief_exact_number(number)}/{basis}'
            if exact:
                return f'{item.currency} {_brief_exact_number(number)}'
            shown = format_compact_currency(number, raw_unit=item.raw_unit,
                                            currency=item.currency, is_base_value=True)
            return shown.replace('-'+item.currency, item.currency+' -', 1)
        if item.unit in {'percent', '%'} or item.raw_unit == '%':
            if exact:
                return f'{_brief_exact_number(number)}%'
            return f'{number:,.1f}%'
        if item.unit in {'count', 'units'}:
            if exact:
                return f'{_brief_exact_number(number)} units'
            return f'{number:,.0f} units'
        if exact:
            return f'{_brief_exact_number(number)} {item.unit or item.raw_unit or ""}'.strip()
        return f'{number:,.1f} {item.unit or item.raw_unit or ""}'.strip()

    label = clean_display_copy(qualified_metric_name(ordered[0]))
    def period(item):
        label = format_canonical_period(item)
        # The shared summary may appear on the web without a slide footer.
        # Keep an explicit source assurance label beside each affected date.
        return label.rstrip('*') + ' (unaudited)' if item.audited_status == 'unaudited' else label

    levels = '; '.join(f'{period(item)} {value(item)}' for item in points)
    pages = sorted({e.page for item in points for e in item.evidence})
    return f'{label}: {levels}.', pages
