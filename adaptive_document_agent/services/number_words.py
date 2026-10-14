"""Canonicalize exact English cardinal notation for checks, never source storage."""
import re

_SMALL = dict(zip(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen '
    'fourteen fifteen sixteen seventeen eighteen nineteen'.split(), range(20)))
_TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))
_SCALES = {'thousand', 'million', 'billion', 'trillion'}
_WORDS = '|'.join((*_SMALL, *_TENS, 'hundred', *_SCALES))
_CARDINAL = re.compile(
    rf'(?i)(?<![\w])(?:{"|".join((*_SMALL, *_TENS))})'
    rf'(?:[\s-]+(?:and[\s-]+)?(?:{_WORDS}))*(?![\w])')


def _under_hundred(words):
    if len(words) == 1:
        return _SMALL.get(words[0], _TENS.get(words[0]))
    if len(words) == 2 and words[0] in _TENS and 0 < _SMALL.get(words[1], 0) < 10:
        return _TENS[words[0]] + _SMALL[words[1]]
    return None


def cardinal_claim_text(text: str) -> str:
    """Parse coefficients below 1000; retain currency, magnitude and other units.

    Complex scale expressions and malformed hundreds stay unrecognized rather
    than authorizing their individual components. Semantic meaning/association
    still requires the independent model review of the exact literal quotation.
    """
    def replace(match):
        words = re.split(r'[\s-]+', match[0].casefold())
        scale = words.pop() if words[-1] in _SCALES else ''
        if any(word in _SCALES for word in words):
            return match[0]
        value = None
        if len(words) >= 2 and words[0] in _SMALL and 0 < _SMALL[words[0]] < 10 and words[1] == 'hundred':
            rest = words[2:]
            if rest[:1] == ['and']:
                rest = rest[1:]
                if not rest:
                    return match[0]
            remainder = _under_hundred(rest) if rest else 0
            if remainder is not None:
                value = _SMALL[words[0]] * 100 + remainder
        else:
            value = _under_hundred(words)
        if value is None:
            if 'hundred' in words:
                return match[0]
            # Adjacent counts need not be a compound: "five four-axis models"
            # and "one and two units" contain distinct literal cardinals.
            return re.sub(r'(?i)\b(?:' + '|'.join((*_SMALL, *_TENS)) + r')\b',
                lambda m: str(_SMALL.get(m[0].casefold(), _TENS.get(m[0].casefold()))), match[0])
        return str(value) + (' ' + scale if scale else '')

    text = _CARDINAL.sub(replace, text)
    return re.sub(r'(?i)(?<![\w-])(?:minus|negative)\s+(?=\d)', '-', text)


def cardinal_numbers(text: str) -> set[str]:
    """Numeric assertions for literal source/claim checks, not chart structure.

    A planner's "three series" or "one source table" describes the selected
    evidence structure, not a measured value in an observation's raw cell.
    Keep cardinal expansion scoped to comparisons with literal quotations.
    """
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    return PresentationPlanValidator._numbers(cardinal_claim_text(text))
