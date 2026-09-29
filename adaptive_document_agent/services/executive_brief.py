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
    return [BriefItem(item.label, item.text, sorted({q.page for q in item.evidence})) for item in brief.items]
