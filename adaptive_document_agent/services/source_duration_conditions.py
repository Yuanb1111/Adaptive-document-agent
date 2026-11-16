"""Match worded duration boundaries to exact source comparators, counts and units."""
import re

from .number_words import cardinal_claim_text

_OPERATORS={
    '>':('older than','more than','greater than','over'),
    '<':('younger than','less than','under'),
    '>=':('at least','no less than','not less than','no younger than','not younger than','not under'),
    '<=':('at most','up to','no more than','not more than','no older than','not older than',
          'not over','within','no later than'),
}
_ALIASES={alias:operator for operator,aliases in _OPERATORS.items() for alias in aliases}
_SEPARATOR=r'[\s-]+'
_OPERATOR='|'.join(_SEPARATOR.join(map(re.escape,alias.split()))
                   for alias in sorted(_ALIASES,key=len,reverse=True))
_CONDITION=re.compile(r'\b(?P<operator>'+_OPERATOR+r')(?P<gap>[\s-]+)'
    r'(?P<number>\d+|[A-Za-z]+(?:[\s-]+[A-Za-z]+){0,8}?)'
    r'[\s-]+(?P<unit>years?|months?|weeks?|days?|hours?)\b',re.I)


def _identity(match: re.Match) -> tuple[str,str,str] | None:
    number=cardinal_claim_text(match['number'])
    if not re.fullmatch(r'\d+',number):return None
    # A spaced minus before a digit is a sign, not compound-word punctuation.
    if match['number'].isdigit() and re.search(r'\s-',match['gap']):return None
    operator=re.sub(r'[\s-]+',' ',match['operator']).casefold()
    return _ALIASES[operator],number,match['unit'].casefold().rstrip('s')


def mask_worded_duration_conditions(text: str,proof: str) -> str:
    """Only notation is reconciled; source population/meaning still needs review."""
    owned={identity for match in _CONDITION.finditer(proof) if (identity:=_identity(match))}
    return _CONDITION.sub(lambda match:' ' if not re.search(r'\d',match['number'])
                          and _identity(match) in owned else match[0],text)
