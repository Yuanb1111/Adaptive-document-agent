"""Recognize explicit dates that clarify an already stated relative comparison."""
import re
from datetime import date

from adaptive_document_agent.extraction.period_header_geometry import month_count
from .brief_audit_scope import _DURATION, _PERIOD, _calendar_date, _period_keys, source_audit_scope

_RELATIVE_YEAR = re.compile(r'\b(?:a year earlier|one year earlier|the prior[- ]year period|'
                            r'the previous[- ]year period|the same period (?:a year earlier|last year)|'
                            r'the year[- ]ago period)\b', re.I)


def period_clarification_options(item, result, *, inventory=None):
    """Bind a relative prior year to complete quoted source columns, never any year.

    This supplies candidate spellings to the writer. It does not authorize new
    measurements, table cells, or semantic claims; all normal gates still run.
    """
    inventory = source_audit_scope(item, result) if inventory is None else inventory
    options = []
    for relative in _RELATIVE_YEAR.finditer(item.text):
        prefix = item.text[:relative.start()]
        # Do not lend a date across a different sentence or independent clause.
        boundary = max([0, *[m.end() for m in re.finditer(r'[.!?](?!\d)\s+|[;\n]', prefix)]])
        before = [m for m in _PERIOD.finditer(prefix, boundary) if not m['year']]
        # A later explicit endpoint owns "a year earlier"; earlier independent
        # comparisons in the same sentence cannot make that endpoint ambiguous.
        before = before[-1:]
        for table in inventory:
            columns = table['columns']
            declared = {re.sub(r'\s+', '', column['period']).upper() for column in columns}
            current = {key for match in before for key in _period_keys(match, columns)} & declared
            if len(current) != 1:
                continue
            endpoint = next(iter(current))
            year = re.search(r'(?:19|20)\d{2}', endpoint)
            if year is None:
                continue
            prior = endpoint[:year.start()] + str(int(year[0]) - 1) + endpoint[year.end():]
            source = [column for column in columns
                      if re.sub(r'\s+', '', column['period']).upper() == prior]
            if not source:
                continue
            statuses = {column['status'] for column in source}
            option = {'relative_phrase': relative[0], 'current_period': endpoint,
                      'clarified_prior_period': prior, 'source_page': table['page'],
                      'source_table_id': table['table_id'],
                      'date_aliases': sorted({alias for column in source for alias in column['date_aliases']}),
                      'audit_status': next(iter(statuses)) if len(statuses) == 1 else 'unknown'}
            if option not in options:
                options.append(option)
    return options


def _flow_identity(match):
    """A literal complete flow period, including its actual closing date."""
    if not match['flow']:
        return None
    duration = re.match(rf'({_DURATION})\s+months?', match[0], re.I)
    day = _calendar_date(re.split(r'\bended\s+', match[0], flags=re.I)[-1])
    if day is None:
        return None
    return month_count(duration[1]), day.isoformat()


def _label_duration(match):
    if not match['label']:
        return None
    label = re.sub(r'\s+', '', match[0]).upper()
    months = re.fullmatch(r'(1[0-2]|[1-9])M((?:19|20)\d{2})', label)
    if months:
        return int(months[1]), months[2], None
    half = re.fullmatch(r'(?:([12])H|H([12]))((?:19|20)\d{2})', label)
    return (6, half[3], '-06-30' if (half[1] or half[2]) == '1' else '-12-31') if half else None


def _standalone_period(match):
    text = match.string
    return ((not match.start() or not text[match.start() - 1].isalnum())
            and (match.end() == len(text) or not text[match.end()].isalnum()))


def original_period_identities(item, inventory, *, result=None):
    """Bind aliases of displayed periods, without making duration a free quantity.

    A full original period supplies its closing date. A compact original label
    needs one unique complete date in its own literal evidence or verified source
    column; a nearby year or another table cannot lend a closing date.
    """
    original = [match for match in _PERIOD.finditer(' '.join(item.text.split())) if _standalone_period(match)]
    identities = {_flow_identity(match) for match in original if match['flow']}
    identities.discard(None)
    source = {_flow_identity(match) for quote in item.evidence
              for match in _PERIOD.finditer(' '.join(quote.text.split()))
              if match['flow'] and _standalone_period(match)}
    source.discard(None)
    from .brief_period_geometry import quoted_table_period_identities
    source.update(quoted_table_period_identities(item, result, inventory))
    for match in original:
        label = _label_duration(match)
        if label is None:
            continue
        months, year, suffix = label
        dates = {day for duration, day in source
                 if duration == months and day.startswith(year) and (not suffix or day.endswith(suffix))}
        for table in inventory:
            for column in table['columns']:
                if not (_period_keys(match, [column]) & {re.sub(r'\s+', '', column['period']).upper()}):
                    continue
                for alias in column['date_aliases']:
                    try:
                        day = date.fromisoformat(alias).isoformat()
                    except ValueError:
                        continue
                    if day.startswith(year) and (not suffix or day.endswith(suffix)):
                        dates.add(day)
        if len(dates) == 1:
            identities.add((months, next(iter(dates))))
    return identities


def quantity_text_with_bound_dates(text, options, inventory, *, original_periods=()):
    """Mask only complete prior-period labels backed by the relative comparison.

    Existing complete period aliases are masked symmetrically in original and
    candidate copy. A bare year/count, new closing date or changed duration is
    never removed by that alias binding.
    """
    allowed = {option['clarified_prior_period'] for option in options}
    columns = [column for table in inventory for column in table['columns']]
    def replace(match):
        if not _standalone_period(match):
            return match[0]
        identity = _flow_identity(match)
        if not match['year'] and _period_keys(match, columns) & allowed:
            # A duration/year key alone does not authorize a different closing
            # date. Complete prior-period spellings retain the source's date.
            if identity is None or any(identity[1] in option['date_aliases'] for option in options
                                        if option['clarified_prior_period'] in _period_keys(match, columns)):
                return ' '
        if identity is not None and identity in original_periods:
            return ' '
        label = _label_duration(match)
        if label:
            months, year, suffix = label
            dates = {day for duration, day in original_periods if duration == months and day.startswith(year)
                     and (not suffix or day.endswith(suffix))}
            if len(dates) == 1:
                return ' '
        return match[0]
    return _PERIOD.sub(replace, text)
