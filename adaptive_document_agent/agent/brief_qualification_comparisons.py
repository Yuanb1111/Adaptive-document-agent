"""Validate the baseline of the same original, dated category-share comparison."""
import re
from decimal import Decimal
from adaptive_document_agent.services.calendar_claims import literal_calendar_dates
from adaptive_document_agent.services.number_words import cardinal_claim_text
from adaptive_document_agent.services.source_quotes import normalize_quote
from .brief_reviewed_qualifications import _bounds, _THRESHOLD, _threshold, _typed_quantities


_NUM = r'\d+(?:\.\d+)?'
_UP = r'increased|rose|risen|grew|grown|climbed'
_DOWN = r'decreased|declined|fell|fallen|dropped'
_VERB = re.compile(r'\b(?:' + _UP + '|' + _DOWN + r')\b', re.I)
_FORWARD = re.compile(rf'\bfrom\s+(?P<base>{_NUM}\s*%)\s+to\s+(?P<end>{_NUM}\s*%)', re.I)
_REVERSE = re.compile(rf'(?P<end>{_NUM}\s*%)(?:\s+(?:of\s+)?[a-z][a-z -]{{0,45}})?\s*'
                      rf'\((?:from|vs\.?|versus)\s+(?P<base>{_NUM}\s*%)\)', re.I)
_BASIS = re.compile(r'\b(?:to|of)\s+(?:the\s+)?(gross|net|total)\s+([a-z][a-z-]+)\b', re.I)


def _rate(text):
    return Decimal(text.strip().rstrip('%').strip())


def _direction(verb):
    return 1 if re.fullmatch(_UP, verb, re.I) else -1


def comparison_options(scopes, joined, failures):
    """Keep internal evidence separate from the already-paid writer request."""
    annotated = {}
    for i, options in scopes.items():
        annotated[i] = {}
        for ref, row in options.items():
            pairs = []
            proof = row['literal_proof']
            source = ' '.join(proof.split())
            owned = set(map(tuple, row['typed_quantities']))
            for match in _FORWARD.finditer(source):
                start, end = _rate(match['base']), _rate(match['end'])
                if start == end or ('', str(end), '%') not in owned:
                    continue
                nearby = re.split(r'[.;!?]\s+', source[:match.start()])[-1]
                verbs = list(_VERB.finditer(nearby))
                if not verbs or nearby[verbs[-1].end():].strip() or _direction(verbs[-1][0]) != (1 if end > start else -1):
                    continue
                categories = _bounds([nearby], _THRESHOLD, _threshold) & set(map(tuple,row['duration_thresholds']))
                bases = _BASIS.findall(nearby)
                if len(categories) != 1 or not bases:
                    continue
                requested_dates = set().union(*(literal_calendar_dates(reason) for reason in failures[i]
                    if ('', str(end), '%') in _typed_quantities(reason)))
                # The reviewer must identify the endpoint and its date. Its
                # original continuous paragraph must actually supply that date.
                for alias in joined[i].values():
                    full = alias['literal_proof']
                    if alias['page'] != row['page'] or normalize_quote(proof) not in normalize_quote(full):
                        continue
                    for paragraph in re.split(r'\n\s*\n', full):
                        normal = ' '.join(paragraph.split())
                        position = normal.find(match[0])
                        if position < 0 or normal[max(0, position-len(nearby)):position].strip() != nearby.strip():
                            continue
                        dates = literal_calendar_dates(normal[:position])
                        if dates and max(dates) in requested_dates:
                            pairs.append(dict(base=str(start), end=str(end), date=max(dates),
                                category=next(iter(categories)), basis=tuple(x.lower() for x in bases[-1])))
            annotated[i][ref] = {**row, 'original_rate_comparisons':pairs} if pairs else row
    return annotated


def mask_comparison_baselines(text, pairs):
    """A baseline is licensed only inside its owned pair, date, scope and direction."""
    pieces = re.split(r'([;!?]\s*|(?<!\d)\.\s+)', text)
    for i in range(0, len(pieces), 2):
        clause = pieces[i]
        dates = literal_calendar_dates(clause)
        for pattern in (_FORWARD, _REVERSE):
            spans = []
            for m in pattern.finditer(clause):
                own_categories = list(_THRESHOLD.finditer(cardinal_claim_text(clause[:m.start()])))
                for pair in pairs:
                    if (_rate(m['base']) != Decimal(pair['base']) or _rate(m['end']) != Decimal(pair['end'])
                            or dates != {pair['date']} or not own_categories
                            or tuple(pair['category']) != _threshold(own_categories[-1])):
                        continue
                    basis, noun = pair['basis']
                    # A compact standalone basis can inherit the selected
                    # category. Any explicitly named denominator must match.
                    named = list(re.finditer(rf'\b{re.escape(basis)}\b(?:\s+([a-z]+))?', clause, re.I))
                    if not named or any(n[1] and n[1].lower() != noun for n in named):
                        continue
                    verbs = list(_VERB.finditer(clause[:m.start()]))
                    if verbs and _direction(verbs[-1][0]) != (1 if _rate(m['end']) > _rate(m['base']) else -1):
                        continue
                    spans.append(m.span('base'))
                    break
            for start, stop in reversed(spans):
                clause = clause[:start] + ' ' * (stop-start) + clause[stop:]
        pieces[i] = clause
    return ''.join(pieces)
