"""Validation-only quantity syntax; literal page text and authored copy stay intact."""
import re

from .number_words import cardinal_claim_text

# An indefinite singular is lexical quantity notation. The independent meaning
# reviewer must still establish what the noun denotes and its actual scope.
# Indefinite plural/aggregate expressions do not denote a literal count of one.
_ARTICLE = re.compile(
    r'(?i)(?<![\w])(?:a|an)\s+(?!(?:few|little|lot|lots|number|couple|pair|dozen|'
    r'variety|range)\b)(?=[A-Za-z])')
_NUMBER = r'[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_CURRENCY = r'(?:US\$|HK\$|RMB|CNY|CNH|USD|HKD|SGD|GBP|EUR|JPY|AUD|CAD|CHF|人民币|美元|港元|欧元|[$€£¥￥])'
_SCALE = r'(?:trillion|billion|million|thousand|bn|mn|[mkb]|万亿|十亿|百万|亿|万|千)'
_BASIS = r'(?:\s+per\s+[A-Za-z][\w-]*(?:\s*/\s*[A-Za-z][\w-]*)*|\s*/\s*[A-Za-z][\w-]*(?:\s*/\s*[A-Za-z][\w-]*)*)'
_RANGE = re.compile(
    rf'(?i)(?<![\w.])(?P<currency>{_CURRENCY})\s*(?P<first>{_NUMBER})\s*'
    rf'(?:[–—-]|\bto\b)\s*(?P<last>{_NUMBER})\s*'
    rf'(?P<scale>{_SCALE})(?![A-Za-z])(?P<basis>{_BASIS})?')


def literal_quantity_text(text: str, *, source: bool = False) -> str:
    """Normalize only literal count/range notation, never infer missing metadata.

    ``a device`` and ``one device`` retain the same noun for semantic review.
    A monetary range repeats only its explicitly shared currency, scale and
    denominator. Each endpoint must separately pass the existing source checks.
    """
    # Source singular grammar can support an explicit "one" claim. An author
    # adding an ordinary indefinite article does not introduce a numeric claim.
    if source:
        text = _ARTICLE.sub('1 ', text)
    else:
        text = re.sub(rf'(?i)(?<![\w])(?:a|an)\s+(?={_SCALE}\b)', '1 ', text)
    text = cardinal_claim_text(text)

    def expand(match):
        suffix = match['scale'] + (match['basis'] or '')
        return (f"{match['currency']}{match['first']} {suffix} to "
                f"{match['currency']}{match['last']} {suffix}")

    return _RANGE.sub(expand, text)


def literal_quantity_numbers(text: str, *, source: bool = False) -> set[str]:
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    return PresentationPlanValidator._numbers(literal_quantity_text(text, source=source))
