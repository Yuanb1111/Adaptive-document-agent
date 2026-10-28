"""Literal, independently reviewed links from assurance scope to original tables."""
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from adaptive_document_agent.models.executive_brief import BriefQuote
from adaptive_document_agent.services.source_quotes import normalize_quote


class AuditPageLabelQuote(BriefQuote):
    """Printed page markers may be shorter than normal supporting prose."""
    text: str = Field(min_length=1, max_length=100)


class AuditUnitQuote(BriefQuote):
    """A complete unit declaration can be shorter than supporting prose."""
    text: str = Field(min_length=1, max_length=1800, description=
        'Literal complete unit declaration for the exact row and column; short '
        'unit labels are valid. Preserve source spelling, scale and currency.')

    @field_validator('text')
    @classmethod
    def require_unit_text(cls, text):
        if not _normal(text):
            raise ValueError('Unit evidence cannot be empty or whitespace.')
        return text


class AuditScopeQuote(BriefQuote):
    """Scope prose or a supporting printed marker, checked against its source."""
    text: str = Field(min_length=1, max_length=1800, description=
        'Literal scope prose, or a standalone printed page marker. Only printed '
        'page markers may be shorter than 8 characters; they do not establish assurance.')

    @field_validator('text')
    @classmethod
    def require_prose_or_marker(cls, text):
        if not _normal(text):
            raise ValueError('Scope evidence cannot be empty or whitespace.')
        if len(text.strip()) < 8 and _address(_printed_label(text)) is None:
            raise ValueError('Short scope evidence must be a printed page marker, not shortened prose.')
        return text


class AuditPageLabelError(ValueError):
    """Recheck reviewer-owned page proof before deciding on writer correction."""


class AuditPageCoverage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page: int = Field(ge=1)
    basis: Literal['explicit_page_range', 'direct_table_qualification']
    scope_quote: BriefQuote
    range_start_label: str | None = None
    range_end_label: str | None = None
    covered_page_label: str | None = None
    page_label_quote: AuditPageLabelQuote | None = None


class AuditCoveredSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    covered_value_quote: BriefQuote
    covered_header_quote: BriefQuote
    covered_unit_quote: AuditUnitQuote
    page_coverage: list[AuditPageCoverage] = Field(min_length=1, max_length=3)


MEASURE_IDENTITY_INSTRUCTIONS = (
    'Interpret each target using its full retained identity: metric_original/metric_canonical, '
    'dimensions, category_dimensions, parent_section and literal evidence row_label together. '
    'A metric may name a broader parent measure while its category and source row identify the '
    'specific component. Do not mistake a component for its parent total, or reject a supported '
    'component merely because its broader metric label differs from the counterpart row. '
    'The model must establish the exact semantic correspondence from original source rows and '
    'context; matching values alone do not establish identity. source_metric must be the literal '
    'counterpart row name for that same retained component. Never rename retained observations, '
    'change their category/value/period or substitute a total to make an assurance binding fit. '
    'If the retained identity genuinely conflicts with the source, retain a source-specific '
    'unknown rather than proposing an observation edit. ')


COUNTERPART_REVIEW_INSTRUCTIONS = (
    'Every accepted verdict MUST include covered_source, independently quoting the covered original '
    'table row (covered_value_quote), its exact period column (covered_header_quote) and literal unit '
    '(covered_unit_quote). These must corroborate the proposal value_quote/header_quote/unit_quote '
    'on their respective source pages, preserving the exact metric, signed raw value, period and unit. '
    'target_quote is only the original observation; a summary outside the assurance scope is not '
    'a covered counterpart. Provide exactly one page_coverage entry for EACH distinct counterpart '
    'quote page. Each scope_quote must be a literal part of the proposed scope_evidence. For '
    'explicit_page_range, quote the explicit covered range, supply its literal range_start_label '
    'and range_end_label, and the covered_page_label with a literal standalone page_label_quote '
    'from that source page (printed labels, not invented PDF-number offsets). For '
    'direct_table_qualification, quote an explicit assurance declaration/qualifier applying to that '
    'exact table and period on the SAME source page; leave all page-label fields null. Do not use '
    'this basis for a generic entity or period statement or an unqualified table. In the verdict '
    'reason explain exact row/column correspondence and assurance ownership, including comparative '
    'qualifiers; matching entity, year or amount alone is insufficient. The original observation '
    'page may also be the counterpart only when this complete coverage chain includes it. If no '
    'explicit page-range or direct table qualification establishes the counterpart, reject the '
    'binding and retain an independently reviewed unknown instead of guessing. Rejected verdicts '
    'may omit covered_source. Never invent a counterpart for unresolved IDs.'
)


def _normal(value):
    return normalize_quote(value or '').casefold()


def _label(value):
    """Normalize typography only; the model identifies the source page labels."""
    value = unicodedata.normalize('NFKC', value or '').casefold()
    return re.sub(r'\s+', '', value.translate(str.maketrans('–—−', '---')))


def _address(value):
    match = re.fullmatch(r'(.*?)(\d+)', _label(value))
    return (match[1], int(match[2])) if match else None


def _printed_label(text):
    return _label(text).strip('-–—()[]{}:.,')


def literal_standalone_page_label(quote, pages):
    """Check marker syntax and a whole source line; infer no page scope or status."""
    printed = _printed_label(quote.text)
    source = pages.get(quote.page, '')
    return (_address(printed) is not None
            and bool(_normal(quote.text)) and _normal(quote.text) in _normal(source)
            and any(_printed_label(line) == printed for line in source.splitlines()))


def _validate_page_coverage(coverage, binding, pages):
    scope = coverage.scope_quote
    if (not _normal(scope.text) or _normal(scope.text) not in _normal(pages.get(scope.page, ''))
            or not any(scope.page == q.page and _normal(scope.text) in _normal(q.text)
                       for q in binding.scope_evidence)):
        raise ValueError('Covered counterpart scope_quote must be literal proposed scope evidence.')
    label_fields = (coverage.range_start_label, coverage.range_end_label,
                    coverage.covered_page_label, coverage.page_label_quote)
    if coverage.basis == 'direct_table_qualification':
        if scope.page != coverage.page or any(value is not None for value in label_fields):
            raise ValueError('Direct table qualification must be on its exact counterpart page without page-range fields.')
        return
    if any(value is None for value in label_fields):
        raise ValueError('Explicit page-range coverage requires both endpoints and a literal counterpart page label.')
    start, end, current = map(_address, label_fields[:3])
    if (None in (start, end, current) or start[0] != end[0] or start[0] != current[0]
            or not start[1] <= current[1] <= end[1]):
        raise ValueError(
            'The counterpart printed page label must lie within the same explicit covered page range. '
            f'Physical page {coverage.page}: covered_page_label={coverage.covered_page_label!r}; '
            f'claimed range={coverage.range_start_label!r} to {coverage.range_end_label!r}; '
            f'page_label_quote.text={coverage.page_label_quote.text!r}. '
            'This proposed counterpart is not covered by that range. Do not change its printed label '
            'or infer assurance from a common entity, period or amount. The writer must select a '
            'different exact covered source row or retain a source-specific unresolved disposition '
            'for independent review. The reviewer must reject unsupported coverage, not relabel it.')
    # Range membership is arithmetic, never an inferred PDF/printed-page offset.
    scope_text = _label(scope.text)
    range_pattern = (r'(?<!\d)' + re.escape(_label(coverage.range_start_label))
                     + r'(?:to|through|[-~至到])' + re.escape(_label(coverage.range_end_label))
                     + r'(?!\d)')
    if not re.search(range_pattern, scope_text):
        raise ValueError('The assurance scope must literally state the proposed covered page range.')
    quote = coverage.page_label_quote
    printed = _printed_label(quote.text)
    if (quote.page != coverage.page or not literal_standalone_page_label(quote, pages)
            or printed != _label(coverage.covered_page_label)):
        raise AuditPageLabelError(
            'The counterpart page label must be a literal standalone source-page marker. '
            f'Physical page {coverage.page}: declared covered_page_label={coverage.covered_page_label!r}; '
            f'page_label_quote.page={quote.page}, page_label_quote.text={quote.text!r}. '
            'Recheck the original page footer/header and make the declared label and literal quote agree; '
            'do not infer a printed label from the physical page number or change the proposed binding. '
            'If the actual printed page is outside the quoted assurance range, reject this binding '
            '(accepted=false, covered_source=null). Do not assign another page\'s label to make it fit; '
            'a missing covered counterpart is a substantive rejection, not a page-label typo.')


def validate_covered_sources(draft, review, context):
    """An accepted boolean cannot substitute for a source-bound counterpart."""
    from .report_audit_scope import _period_in_header
    if context is None:
        raise ValueError('Independent audit counterpart validation requires the exact source context.')
    pages = {page['page']: page['text'] for page in context['source_pages']}
    verdicts = {verdict.observation_id: verdict for verdict in review.verdicts}
    for binding in draft.bindings:
        source = verdicts[binding.observation_id].covered_source
        if source is None:
            raise ValueError(f'{binding.observation_id}: accepted audit binding requires an independently covered source table.')
        pairs = [('covered_value_quote', 'value_quote'), ('covered_header_quote', 'header_quote'),
                 ('covered_unit_quote', 'unit_quote')]
        for reviewed_name, proposed_name in pairs:
            quote = getattr(source, reviewed_name)
            if quote.page != getattr(binding, proposed_name).page:
                raise ValueError(f'{binding.observation_id}: {reviewed_name} must corroborate the exact proposed counterpart page.')
            if _normal(quote.text) not in _normal(pages.get(quote.page, '')):
                raise ValueError(f'{binding.observation_id}: {reviewed_name} must be literal source evidence.')
        if (not _normal(binding.source_metric) in _normal(source.covered_value_quote.text)
                or not _normal(binding.source_raw_value) in _normal(source.covered_value_quote.text)
                or not _period_in_header(binding.period, source.covered_header_quote.text)
                or not _normal(binding.source_unit) in _normal(source.covered_unit_quote.text)):
            raise ValueError(f'{binding.observation_id}: independently covered row, period and unit must match the exact mapped measure.')
        expected = {getattr(source, name).page for name, _ in pairs}
        actual = [item.page for item in source.page_coverage]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError(f'{binding.observation_id}: explicit assurance coverage must account for every counterpart quote page exactly once.')
        for coverage in source.page_coverage:
            _validate_page_coverage(coverage, binding, pages)
