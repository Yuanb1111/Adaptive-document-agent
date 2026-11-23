"""Expand only unambiguous, explicitly ranged metric coordination in copy."""
import re


_VERBS = r'(?:rose|fell|increased|decreased|grew|declined|widened|narrowed)'
_ASSURANCE = r'(?:\s+\((?:un)?audited\))?'


def _primary_series(rows):
    """Return one exact source row-series identity and its period labels."""
    from adaptive_document_agent.document_model.period_semantic_validator import extract_period_basis

    if not rows:
        return None
    metrics, tables, source_rows, contexts = set(), set(), set(), set()
    periods = []
    period_context = {}
    for row in rows:
        metric = row.get('metric_original')
        period = row.get('period')
        table = row.get('table_id')
        row_id = row.get('row_id')
        if not metric or not isinstance(period, str) or not period.strip() or not table or row_id is None:
            return None
        metrics.add(metric)
        tables.add(table)
        source_rows.add(row_id)
        dimensions = row.get('dimensions') or {}
        contexts.add((row.get('entity'),
            tuple(sorted((key, value) for key, value in dimensions.items() if key != 'period_basis')),
            tuple(sorted((row.get('category_dimensions') or {}).items())),
            row.get('unit'), row.get('unit_scale'),
            row.get('raw_unit'), row.get('unit_family'), row.get('currency'),
            row.get('row_operator')))
        period = period.strip()
        periods.append(period)
        period_context[period] = (row.get('audited_status', 'unknown'), row.get('period_type'),
                                  row.get('period_basis'), dimensions.get('period_basis'),
                                  extract_period_basis(period))
    if (len(metrics) != 1 or len(tables) != 1 or len(source_rows) != 1
            or len(contexts) != 1
            or len(periods) < 2 or len(periods) != len(set(periods))):
        return None
    return next(iter(metrics)), periods, period_context


def _expand_sentence(sentence, metric, periods, period_context):
    from adaptive_document_agent.services.calendar_claims import bound_period_dates
    from adaptive_document_agent.document_model.series import period_sort_key

    canonical = [bound_period_dates(period, periods) for period in periods]
    if any(not period for period in canonical) or len(set(canonical)) != len(canonical):
        return sentence
    period_rows = sorted(zip(canonical, periods, strict=True), key=lambda item: period_sort_key(item[0]))
    source_period_by_label = {label: source for label, source in period_rows}
    period_alt = '(?:' + '|'.join(re.escape(value) for value in
        sorted(canonical, key=len, reverse=True)) + ')'
    period_token = period_alt + _ASSURANCE
    predicate = rf'(?P<verb>{_VERBS})\s+from\s+(?P<start>{period_token})\s+to\s+(?P<end>{period_token})'
    # Later legs may inherit the first verb, but each must still state both
    # endpoints explicitly. Never fill an omitted or relative endpoint.
    predicate_plain = rf'(?:(?:{_VERBS})\s+)?from\s+(?:{period_token})\s+to\s+(?:{period_token})'
    later_predicate = rf'(?:(?P<verb>{_VERBS})\s+)?from\s+(?P<start>{period_token})\s+to\s+(?P<end>{period_token})'
    match = re.fullmatch(
        rf'(?P<leading>\s*)(?P<subject>.+?)\s+(?P<first>{predicate})'
        rf'(?P<rest>(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+){predicate_plain})+)'
        rf'(?P<ending>[.!?]?\s*)', sentence, re.I)
    if not match or match['subject'].strip().casefold() != metric.casefold():
        return sentence

    positions = {label: index for index, (label, _) in enumerate(period_rows)}
    first = re.fullmatch(predicate, match['first'], re.I)
    clauses = [first, *re.finditer(later_predicate, match['rest'], re.I)]
    parsed = []
    for found in clauses:
        endpoints = []
        bases = []
        for key in ('start', 'end'):
            token = found[key]
            assurance = re.search(r'\s+\((un)?audited\)$', token, re.I)
            base = token[:assurance.start()] if assurance else token
            position = positions.get(base)
            if position is None:
                return sentence
            source_period = source_period_by_label[base]
            expected, *basis = period_context[source_period]
            if assurance:
                claimed = 'unaudited' if assurance[1] else 'audited'
                if expected.casefold() != claimed:
                    return sentence
            endpoints.append(position)
            bases.append(basis)
        if endpoints[0] >= endpoints[1] or bases[0] != bases[1]:
            return sentence
        parsed.append((found['verb'] or first['verb'], found['start'], found['end']))

    rebuilt = match['leading'] + match['subject'] + ' ' + match['first']
    for verb, start, end in parsed[1:]:
        rebuilt += '. ' + match['subject'] + ' ' + verb + ' from ' + start + ' to ' + end
    return rebuilt + match['ending']


def expand_coordinated_directions(message: str, primary_rows: list[dict], companion_rows=()) -> str:
    """Repeat a uniquely bound metric across exact, comparable explicit ranges.

    Only complete sentences with a literal exact metric subject and finite
    direction/range clauses are considered. Any ambiguity leaves the input
    byte-for-byte unchanged; downstream numeric and direction validators remain
    authoritative for each expanded sentence.
    """
    if not isinstance(message, str):
        return message
    if any(quote in message for quote in ('"', '“', '”', '‘', '’')):
        return message
    primary_locations = {(row.get('table_id'), row.get('row_id'), row.get('metric_original'))
                         for row in primary_rows}
    bound_companions = [row for row in companion_rows
                        if (row.get('table_id'), row.get('row_id'), row.get('metric_original')) in primary_locations]
    series = _primary_series([*primary_rows, *bound_companions])
    if series is None:
        return message
    metric, periods, period_context = series
    # ISO periods and ordinary report labels contain no sentence punctuation;
    # preserve all surrounding copy by splitting only at complete boundaries.
    pieces = re.split(r'(?<=[.!?])(?=\s+[A-Z])', message)
    return ''.join(_expand_sentence(piece, metric, periods, period_context) for piece in pieces)
