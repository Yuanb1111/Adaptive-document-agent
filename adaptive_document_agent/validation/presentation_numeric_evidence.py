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
    if item.unit == 'percent' or item.unit_family == 'percentage':
        if item.value is not None:
            fields.append(f'{item.value}%')
        if re.fullmatch(r'[+-]?[\d,.]+', item.raw_value.strip()):
            fields.append(item.raw_value + '%')
    return fields


_MONEY = re.compile(
    r"(?<![\w.])(?:(?P<currency>US\$|HK\$|S\$|RMB|CNY|CNH|USD|HKD|SGD|GBP|EUR|JPY|AUD|CAD|CHF|[$£€¥])\s*)?"
    r"(?P<number>[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?:\s*(?P<scale>thousand|million|billion|trillion|bn|mn|[kmb]))?(?!\w|[.,]\d)", re.I)
_MONEY_SCALES = {"": 1, "k": 1_000, "thousand": 1_000, "m": 1_000_000,
                 "mn": 1_000_000, "million": 1_000_000, "b": 1_000_000_000,
                 "bn": 1_000_000_000, "billion": 1_000_000_000, "trillion": 10**12}
_ALIASES = {"RMB": "CNY", "CNH": "CNY", "US$": "USD", "$": "USD", "HK$": "HKD",
            "S$": "SGD", "£": "GBP", "€": "EUR", "¥": "CNY"}
_DECREASE = re.compile(r"\b(?:(?:decrease|decline|reduction|drop) of|(?:decreased|declined|fell|dropped) by)\s*$", re.I)
_CASH_USE = re.compile(r"\s+used in (?:operations|(?:operating|investing|financing) activities)\b", re.I)


def _currency(value):
    code = (value or "").upper()
    return _ALIASES.get(code, code)


def checked_money_amounts(text, observations, calculations=()):
    """Yield the amount, its support status and any required calculation IDs."""
    monetary = {o.id: o for o in observations if o.value is not None and o.currency
                and o.unit_family in {"generic", "currency"} and o.unit in {None, "currency", o.currency}
                and not split_unit_basis(o.raw_unit)[1]}
    amounts = [(o.value, _currency(o.currency), None) for o in monetary.values()]
    changes = [(c["value"], _currency(c["currency"]), c["id"]) for c in calculations
               if c.get("currency") and set(c["observation_ids"]) <= monetary.keys()]
    currencies = {code for _, code, _ in amounts + changes}
    for match in _MONEY.finditer(text):
        if not (match["currency"] or match["scale"]):
            continue
        currency = _currency(match["currency"])
        if not currency and len(currencies) == 1:
            currency = next(iter(currencies))
        literal = match["number"].replace(",", "").replace("−", "-")
        claimed = Decimal(literal)
        before, after = text[:match.start()].rstrip(), text[match.end():]
        decrease = _DECREASE.search(before)
        cash_use = _CASH_USE.match(after)
        negative = re.search(r"(?:\bnegative|(?<!\w)[−-])$", before, re.I)
        positive = re.search(r"(?:\bpositive|(?<!\w)\+)$", before, re.I)
        conflicting_sign = (positive or literal.startswith("+")) and (negative or cash_use or decrease or claimed < 0)
        if conflicting_sign or re.match(r"\s*(?:[%％/]|per\b)", after, re.I):
            yield match, False, set()
            continue
        if negative or cash_use or decrease:
            claimed = -abs(claimed)
        scale = _MONEY_SCALES[(match["scale"] or "").lower()]
        places = -claimed.as_tuple().exponent
        # A decrease by an amount needs a calculated change, while cash used
        # needs an observed outflow. Neither borrows the other's magnitude.
        candidates = amounts + changes
        if decrease:
            candidates = changes
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
