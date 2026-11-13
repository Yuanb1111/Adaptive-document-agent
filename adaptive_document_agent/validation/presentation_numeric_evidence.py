"""Source-typed numeric fields shared by slide and theme validation."""
import re
from decimal import Decimal, InvalidOperation

from adaptive_document_agent.services.financial_formatter import split_unit_basis


def observation_numeric_fields(item, *, include_context=False):
    """Preserve source numbers; add '%' only for explicitly typed percentages.

    A bare amount, ratio or unrelated observation never licenses a percentage.
    Fields stay separate so a grouped value cannot swallow an adjacent year.
    """
    values = [item.raw_value, item.value, item.period]
    if include_context:
        values.extend((item.entity, item.dimensions))
    fields = [str(value) for value in values if value is not None]
    # Accounting parentheses encode a sign in a raw source cell. Preserve that
    # cell and additionally license its signed spelling, only when the typed
    # observation agrees. This is still the reported unit, not a new amount.
    parenthesized = re.fullmatch(r"\(\s*(\d[\d,]*(?:\.\d+)?)\s*\)", item.raw_value.strip())
    if parenthesized and item.value is not None and item.value < 0:
        fields.append('-' + parenthesized[1])
    if item.unit == 'percent' or item.unit_family == 'percentage':
        if item.value is not None:
            fields.append(f'{item.value}%')
        if re.fullmatch(r'[+-]?[\d,.]+', item.raw_value.strip()):
            fields.append(item.raw_value + '%')
    return fields


_CURRENCY_TOKEN = r"US\$|HK\$|S\$|RMB|CNY|CNH|USD|HKD|SGD|GBP|EUR|JPY|AUD|CAD|CHF|[$£€¥]"
_MONEY = re.compile(
    rf"(?<![\w.])(?P<accounting>\()?\s*(?:(?P<currency>{_CURRENCY_TOKEN})\s*)?"
    r"(?P<number>[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?:\s*(?P<scale>thousand|million|billion|trillion|bn|mn|[kmb]))?"
    r"(?(accounting)\s*\)(?:\s*(?P<outer_scale>thousand|million|billion|trillion|bn|mn|[kmb]))?)"
    r"(?!\w|[.,]\d)", re.I)
_MONEY_SCALES = {"": 1, "k": 1_000, "thousand": 1_000, "m": 1_000_000,
                 "mn": 1_000_000, "million": 1_000_000, "b": 1_000_000_000,
                 "bn": 1_000_000_000, "billion": 1_000_000_000, "trillion": 10**12}
_MONEY_UNIT_DECLARATION = re.compile(
    rf"(?:^[ \t]*|(?P<parenthesis>\())(?P<currency>{_CURRENCY_TOKEN})[ \t]+in[ \t]+"
    r"(?P<scale>unit|thousand|million|billion|trillion)s?[ \t]*(?(parenthesis)\.?\)|[:.])", re.I | re.M)
_ALIASES = {"RMB": "CNY", "CNH": "CNY", "US$": "USD", "$": "USD", "HK$": "HKD",
            "S$": "SGD", "£": "GBP", "€": "EUR", "¥": "CNY"}
_DECREASE = re.compile(r"\b(?:(?:decrease|decline|reduction|drop) of|(?:decreased|declined|fell|dropped) by)\s*$", re.I)
_CASH_USE = re.compile(r"\s+used in (?:operations|(?:operating|investing|financing) activities)\b", re.I)
_CALCULATED_AMOUNT=re.compile(r'\b(?:calculated|computed|recalculated|recomputed)\s+'
    r'(?:signed\s+)?(?P<kind>increase|decrease|change)\s+(?:of|was|is)\s*$',re.I)
_CALCULATED_INTERVAL=re.compile(r'^\s+from\s+(?P<start>(?:FY\s*|[1369]M\s*)?(?:19|20)\d{2}'
    r'(?:-\d{2}-\d{2})?)\s+to\s+(?P<end>(?:FY\s*|[1369]M\s*)?(?:19|20)\d{2}'
    r'(?:-\d{2}-\d{2})?)\b',re.I)


def _currency(value):
    code = (value or "").upper()
    return _ALIASES.get(code, code)


def _money_scale(text, match):
    if match["scale"] or match["outer_scale"]:
        return _MONEY_SCALES[(match["scale"] or match["outer_scale"]).lower()]
    # A visible declaration governs later amounts of the same currency in this
    # paragraph. An explicit suffix always wins, and a new line starts a new scope.
    start = text.rfind("\n", 0, match.start()) + 1
    declarations = list(_MONEY_UNIT_DECLARATION.finditer(text, start, match.start()))
    if declarations and _currency(declarations[-1]["currency"]) == _currency(match["currency"]):
        name = declarations[-1]["scale"].lower()
        return _MONEY_SCALES.get(name, 1)  # "in units" explicitly resets the scale.
    return 1


def checked_money_amounts(text, observations, calculations=()):
    """Yield the amount, its support status and any required calculation IDs."""
    calculations=list(calculations)
    from .calculated_count_change import checked_count_changes
    count_spans={m.span('number') for m,ok,_ in checked_count_changes(text,observations,calculations) if ok}
    monetary = {o.id: o for o in observations if o.value is not None and o.currency
                and o.unit_family in {"generic", "currency"} and o.unit in {None, "currency", o.currency}
                and not split_unit_basis(o.raw_unit)[1]}
    amounts = [(o.value, _currency(o.currency), None) for o in monetary.values()]
    changes = [(c["value"], _currency(c["currency"]), c["id"]) for c in calculations
               if c.get("currency") and set(c["observation_ids"]) <= monetary.keys()]
    currencies = {code for _, code, _ in amounts + changes}
    for match in _MONEY.finditer(text):
        if match.span('number') in count_spans:continue
        bare=not (match['currency'] or match['scale'] or match['outer_scale'])
        declared=None;eligible_calculations=None
        if bare:
            if re.match(r'\s*(?:[%％]|percent(?:age)?\b|pp\b)',text[match.end():],re.I):
                continue  # Percentage evidence has its own typed calculation gate.
            label=_CALCULATED_AMOUNT.search(text[:match.start()])
            if not label or not monetary:
                continue
            start=text.rfind('\n',0,match.start())+1
            declarations=list(_MONEY_UNIT_DECLARATION.finditer(text,start,match.start()))
            interval=_CALCULATED_INTERVAL.match(text[match.end():])
            if not declarations or not interval:
                yield match,False,set()
                continue
            declared=declarations[-1]
            normalize=lambda s:re.sub(r'\s+','',s).casefold()
            ends=[normalize(interval['start']),normalize(interval['end'])]
            sentence=re.split(r'(?<=[.!?])\s+',text[:label.start()])[-1].casefold()
            eligible_calculations=[c for c in calculations
                if c['kind'] in {'absolute_change','yoy_absolute_change'}
                and c.get('currency') and set(c['observation_ids'])<=monetary.keys()
                and [normalize(c['periods'][0]),normalize(c['periods'][-1])]==ends
                and re.search(r'(?<!\w)'+re.escape(c['metric'])+r'(?!\w)',sentence,re.I)
                and (label['kind'].casefold()=='change' or
                     (label['kind'].casefold()=='increase' and c['value']>0) or
                     (label['kind'].casefold()=='decrease' and c['value']<0))]
            if len(eligible_calculations)!=1:
                yield match,False,set()
                continue
        currency = _currency(match["currency"])
        if declared is not None:
            currency=_currency(declared['currency'])
        if not currency and len(currencies) == 1:
            currency = next(iter(currencies))
        literal = match["number"].replace(",", "").replace("−", "-")
        claimed = Decimal(literal)
        if bare and label['kind'].casefold()!='change' and (claimed<=0 or match['accounting']):
            yield match,False,set()
            continue
        before, after = text[:match.start()].rstrip(), text[match.end():]
        decrease = _DECREASE.search(before)
        cash_use = _CASH_USE.match(after)
        negative = re.search(r"(?:\bnegative|(?<!\w)[−-])$", before, re.I)
        positive = re.search(r"(?:\bpositive|(?<!\w)\+)$", before, re.I)
        accounting = bool(match["accounting"])
        conflicting_scale = match["scale"] and match["outer_scale"]
        conflicting_sign = (positive or literal.startswith("+")) and (accounting or negative or cash_use or decrease or claimed < 0)
        if conflicting_scale or conflicting_sign or re.match(r"\s*(?:[%％/]|per\b)", after, re.I):
            yield match, False, set()
            continue
        if accounting or negative or cash_use or decrease:
            claimed = -abs(claimed)
        if bare and label['kind'].casefold()=='decrease':
            claimed=-abs(claimed)
        scale = (_MONEY_SCALES.get(declared['scale'].lower(),1) if declared is not None
                 else _money_scale(text, match))
        places = -claimed.as_tuple().exponent
        # A decrease by an amount needs a calculated change, while cash used
        # needs an observed outflow. Neither borrows the other's magnitude.
        candidates = amounts + changes
        if eligible_calculations is not None:
            candidates=[(c['value'],_currency(c['currency']),c['id']) for c in eligible_calculations]
        if decrease:
            candidates = candidates if eligible_calculations is not None else changes
        elif cash_use:
            candidates = amounts
        try:
            matches = {cid for value, code, cid in candidates
                       if code == currency and (value == 0 or claimed != 0)
                       and round(Decimal(str(value)) / scale, places) == claimed}
        except InvalidOperation:
            matches = set()
        # A directly observed amount needs no derived-value reference.
        yield match, bool(matches), set() if None in matches else matches


_TABLE_CONFIDENCE = re.compile(
    r"\btable(?:[\s-]+extraction)?[\s-]+confidence\b(?:\s+score\b)?\s*"
    r"(?:(?:is|was|of)\s+|[:=]\s*)?"
    r"(?P<score>[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+))(?P<percent>\s*%)?"
    r"(?=\s*(?:$|[;!?)]|[.,](?!\d)))", re.I)


_PAGE_NUMBER = r'(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)'
_PAGE_SPAN = rf'{_PAGE_NUMBER}(?:\s*[-–—]\s*{_PAGE_NUMBER})?'
_PAGE_LIST_END = r'(?=\s*(?:$|[);:!?]|\.(?!\d)))'
_PAGE_AND = r'(?:,\s+|\s+)and\s+'
_PAGE_LIST = (
    rf'{_PAGE_SPAN}(?:(?:,\s+{_PAGE_SPAN})*{_PAGE_AND}{_PAGE_SPAN}(?:{_PAGE_LIST_END}|(?=,\s+))'
    rf'|(?:,\s+{_PAGE_SPAN})+{_PAGE_LIST_END})')
_PAGE_CITATION = re.compile(
    # A single reference must not absorb the amount in "on page 12, 17 people ...".
    # Only a plural marker and a closed list denote several comma-separated references.
    rf'\b(?:(?:pages\s+|pp\.\s*)(?P<list>{_PAGE_LIST})|(?:pages?\s+|pp?\.\s*)(?P<span>{_PAGE_SPAN}))'
    r'(?![\w%]|[.,]\d|[-–—]\d)', re.I)


def check_selection_page_references(reason, cited_pages):
    """Validate physical PDF citations in the rationale without licensing their digits elsewhere."""
    return check_page_references(reason, cited_pages,
        error_prefix='selection reason cites a page outside its retained slide references')


def check_page_references(reason, cited_pages, *, error_prefix='page citation outside the item-bound evidence'):
    """Mask only explicit physical page references after checking their full span."""
    errors = []

    def mask_reference(match):
        for span in re.split(rf'{_PAGE_AND}|,\s+', match['list'] or match['span'], flags=re.I):
            ends = [int(n.replace(',', '')) for n in re.split(r'[-–—]', span)]
            first, last = ends[0], ends[-1]
            if first > last or sum(first <= page <= last for page in cited_pages) != last - first + 1:
                errors.append(f'{error_prefix}: {match[0]}')
                break
        return ' '

    return _PAGE_CITATION.sub(mask_reference, reason), errors


def check_selection_confidence(reason, observations, document):
    """Verify explicit table scores in the rationale without licensing numbers in other claims."""
    matches = list(_TABLE_CONFIDENCE.finditer(reason))
    if not matches:
        return reason, []
    owners = {(e.page, e.table_id) for o in observations for e in o.evidence}
    tables = [(p.page_number, t) for p in document.pages for t in p.tables
              if t.page == p.page_number and (p.page_number, t.table_id) in owners]
    all_inputs_cited = all(o.evidence and
        (not o.table_id or any(e.table_id == o.table_id for e in o.evidence)) for o in observations)
    complete = (bool(owners) and all_inputs_cited
                and owners == {(page, t.table_id) for page, t in tables}
                and all('confidence' in t.model_fields_set for _, t in tables))
    scores = {Decimal(str(t.confidence)) for _, t in tables}
    masked, errors = list(reason), []
    for match in matches:
        multiplier = 100 if match['percent'] else 1
        claimed = Decimal(match['score'].replace(',', ''))
        if complete and {score * multiplier for score in scores} == {claimed}:
            start, end = match.span('score')
            masked[start:end] = ' ' * (end - start)
        else:
            errors.append(f"selection reason has no matching extraction confidence for all cited tables: {match[0]}")
    return ''.join(masked), errors


def mask_finding_amounts(slide, insights, inputs, observations, calculations):
    """Mask grounded occurrences only in verbatim copies of their owning finding."""
    copies = {}
    for iid in slide.insight_ids:
        finding = insights.get(iid)
        ids = set(inputs.get(iid, ()))
        if not finding or not ids:
            continue
        owned = [observations[oid] for oid in ids]
        bound = [calculations[cid] for cid in slide.calculation_ids if cid in calculations
                 and set(calculations[cid]["observation_ids"]) <= ids]
        candidates = {finding.narrative}
        if finding.movement:
            candidates.add(f"{finding.title}: {finding.movement.rstrip('.')}.")
        for copy in candidates.intersection([slide.message, *slide.bullets]):
            if any(bullet == copy and not ids <= set(scope)
                   for bullet, scope in zip(slide.bullets, slide.bullet_observation_ids)):
                continue
            masked = list(copy)
            for match, supported, _ in checked_money_amounts(copy, owned, bound):
                if supported:
                    masked[match.start():match.end()] = " " * len(match[0])
            copies[copy] = "".join(masked)
    return copies


def mask_declared_calculated_amounts(text,observations,calculations):
    """Mask only strict, explicitly labelled amounts with retained calculation IDs."""
    masked=list(text)
    for match,supported,ids in checked_money_amounts(text,observations,calculations):
        if supported and ids and not (match['currency'] or match['scale'] or match['outer_scale']):
            masked[match.start():match.end()]=' '*len(match[0])
    return ''.join(masked)
