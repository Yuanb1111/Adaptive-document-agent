"""Bind source-authored analysis pages to their calculation and companion rows."""
import re

from pydantic import BaseModel, ConfigDict, Field
from adaptive_document_agent.models.executive_brief import BriefQuote

from adaptive_document_agent.services.presentation_evidence import (
    ambiguous_source_table_ids, observation_uses_ambiguous_table)
from .audit_source_layout import audit_source_page


PERIOD_AND_ASSURANCE_RULES = (
    'Use the exact bound period labels, even in parentheses and source attributions. '
    'Do not expand a fiscal-year or interim label into a calendar date. If the levels have '
    'different reporting bases, list their exact dated values separately instead of asserting a '
    'direction across those bases. State a source-attributed driver separately and retain its '
    'literal source scope without turning it into a comparison between incompatible endpoints. '
    'A source-defined named interval must retain its literal name; do not narrow it to the '
    'subset of periods used by the chart comparison. An attributed qualitative explanation '
    'for that broader named scope is distinct from a numeric comparison across unequal durations. '
    'Read a prose citation together with its preceding and following source pages. A continuation '
    'may inherit its period, entity and measure from the preceding paragraph opening, while later '
    'paragraphs on the same page can concern different periods. A driver_quote alone does not '
    'establish that scope. Attribute a driver to the period stated in its own paragraph; a '
    'within-period explanation does not establish a comparison with another period. If the '
    'paragraph scope is unavailable, report the uncertainty instead of supplying an interval. '
    'For source prose without eligible numeric rows, preserve the supported qualitative driver '
    'and its literal period. Use noun phrases describing the source-supported factors and their '
    'positive or negative contribution to that period. Reserve directional predicates '
    '(increase, decrease, higher, lower) for comparisons with bound rows and explicit endpoints; '
    'do not turn prose-only factors into additional numerical trend claims. Do not require '
    'their unbound amounts on the analysis page. '
    'For material source-only qualifications without eligible rows, preserve their qualitative '
    'meaning, including adverse or limiting effects, and distinguish related gross/net or other '
    'populations. Do not require unbound percentages or thresholds. Do not retain uncalibrated '
    'reassurance such as "relatively low" when omitted numeric qualifications materially limit it. '
    'Only use an audit label for a row explicitly marked with that status. Unknown means unmarked. '
    'Never propagate a label to another period or measure based on a shared heading. '
    'When a chart reports CAGR alongside its raw levels, cite the matching reported CAGR companion row. '
    'State the reported CAGR and any recalculated CAGR in separate sentences, with explicit attribution '
    'and the exact start and end years in each sentence. Use the bound original chart unit for the levels. '
    'A Python-calculated CAGR is a derived result, not a source table cell. It may be stated as '
    '"The calculated CAGR was [rate] from [exact start period] to [exact end period]" when the '
    'supplied calculation and its input rows support it. Do not remove such a calculated rate '
    'merely because the source does not report a CAGR cell. Do not relabel it as reported. '
)
_PERIOD_ASSURANCE = re.compile(
    r'(?P<period>\b(?:FY\d{4}|\d{1,2}M\d{4}|\d{4}-\d{2}-\d{2})\b)\s*'
    r'\(\s*(?P<status>unaudited|audited)\s*\)', re.I)


def _check_explicit_period_assurance(text, observations):
    """Reject an adjacent label that has no matching row for the named period."""
    from adaptive_document_agent.services.calendar_claims import bound_period_dates
    by_period = {}
    for observation in observations:
        if observation.period:
            period = bound_period_dates(observation.period, [observation.period])
            by_period.setdefault(period.upper(), set()).add(observation.audited_status)
    for match in _PERIOD_ASSURANCE.finditer(text):
        period, status = match['period'].upper(), match['status'].lower()
        if status not in by_period.get(period, ()):
            raise ValueError(f'{period} has no bound row explicitly marked {status}. '
                             'Keep the exact period and value and remove the unsupported qualifier.')


class RetainedPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=180,
        description='Concise metric and scope label. Put dated direction and trajectory in the message. '
                    'If the title itself asserts a change, it must state both complete comparison dates.')
    message: str = Field(min_length=1, max_length=2000,
        description='Aim for under 900 characters using exact source period labels and shared explicit units. '
                    'Keep material source qualifications and dated components intact. Final physical '
                    'page budgets and rendered text fit are checked separately; never truncate evidence.')
    companion_ids: list[str] = Field(default_factory=list, max_length=40,
        description='Only extra rows used in visible copy. Choose row references from this finding’s '
                    'allowed_companion_rows. Use [] when its primary observations are sufficient.')
    context_evidence: list[BriefQuote] = Field(default_factory=list, max_length=8,
        description='Exact literal quotations from supplied source_pages supporting qualitative '
                    'qualifications or drivers outside the primary row evidence. These do not '
                    'authorize additional numeric claims or companion rows.')


def context_evidence_pages(page, context, result):
    """Bind model-selected qualitative context without expanding numeric eligibility."""
    from adaptive_document_agent.services.source_quotes import normalize_quote
    allowed = {p['page'] for p in context.get('source_pages', [])}
    sources = {p.page_number: normalize_quote(p.text) for p in result.document.pages}
    pages = set()
    for quote in page.context_evidence if page is not None else []:
        text = normalize_quote(quote.text)
        if quote.page not in allowed or not text or text not in sources.get(quote.page, ''):
            raise ValueError('Context evidence must be a literal quote from a supplied source page')
        pages.add(quote.page)
    return pages


def retained_context_citations(result):
    """Recheck persisted quotation provenance for slide/theme validators."""
    from .retained_analysis import selected_record, selection_context, fingerprint, RetainedAnalysisSelection
    record = selected_record(result)
    if not record or not any(d.get('page', {}).get('context_evidence')
                            for d in record['selection']['decisions'] if d.get('page')):
        return {}
    context = selection_context(result)
    if not record.get('source_authoring') or record['input_fingerprint'] != fingerprint(context):
        raise ValueError('Retained qualitative context has stale source bindings')
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    return {d.insight_id: context_evidence_pages(d.page, context, result)
            for d in selection.decisions if d.decision == 'include'}


def page_sources(result, linked):
    from adaptive_document_agent.services.source_citations import evidence_pages
    ids = set().union(*(entry[1] for entry in linked.values()))
    anchors = [o for o in result.observations if o.id in ids]
    pages = {e.page for o in anchors for e in o.evidence}
    for insight, _, _ in linked.values():
        pages.update(evidence_pages(insight, [], document=result.document))
    originals = [p for p in result.document.pages if p.page_number in pages]
    tables = {o.effective_table_id for o in anchors if o.effective_table_id}
    ambiguous = ambiguous_source_table_ids(result)
    companions = [o for o in result.observations if o.effective_table_id in tables
                  and o.value is not None and o.validation_status == 'valid' and o.evidence
                  and not observation_uses_ambiguous_table(o, ambiguous)]
    return dict(source_pages=[audit_source_page(p) for p in originals],
                source_rows=[dict(id=o.id, table_id=o.effective_table_id,
                    metric=o.metric_original, parent=o.parent_section, categories=o.category_dimensions,
                    period=o.period, value=o.raw_value, unit=o.raw_unit, currency=o.currency)
                    for o in companions])


def page_bindings(page, insight, primary, context, result):
    from .presentation_insight_recovery import _numeric_support
    from adaptive_document_agent.services.calendar_claims import bound_period_dates
    context_evidence_pages(page, context, result)
    by_id = {o.id: o for o in result.observations}
    tables = {by_id[k].effective_table_id for k in primary}
    allowed = {r['id'] for r in context['source_rows'] if r['table_id'] in tables}
    ids = primary | set(page.companion_ids)
    foreign = set(page.companion_ids) - allowed - primary
    primary_series = {(by_id[k].effective_table_id, by_id[k].metric_original) for k in primary}
    foreign.update(k for k in set(page.companion_ids) & allowed
                   if (owner := by_id[k].dimensions.get('chart_reported_cagr'))
                   and (by_id[k].effective_table_id, owner) not in primary_series)
    if foreign:
        raise ValueError(f'{insight.id}: companion rows outside its source tables: {sorted(foreign)}')
    if len(ids) > 40:
        raise ValueError(f'{insight.id}: {len(ids)} distinct observations exceed the 40-row slide limit')
    obs = [by_id[k] for k in ids]
    periods = [o.period for o in obs]
    title, copy = (bound_period_dates(s, periods) for s in (page.title, page.message))
    for field, text in [('title', title), ('message', copy)]:
        diagnostics = []
        if not _numeric_support(text, obs, diagnostics=diagnostics):
            raise ValueError(f'{insight.id}.{field}: amount, date or rate outside its bound evidence: {text}. '
                f'Details: {diagnostics}. Bind any used table components to their exact '
                'allowed companion rows. Do not introduce amounts found only in unbound source prose; '
                'retain the source explanation without that additional numeric claim. Preserve signed raw outflows.')
        try:
            _check_explicit_period_assurance(text, obs)
        except ValueError as exc:
            raise ValueError(f'{insight.id}.{field}: {exc}') from exc
    return title, copy, ids


class AuthoredPageErrors(ValueError):
    def __init__(self, by_insight: dict[str, list[str]]):
        self.by_insight = by_insight
        super().__init__('\n'.join(f'{iid}: {issue}' for iid, issues in by_insight.items() for issue in issues))


def validate_authored_pages(selection, context, result):
    from adaptive_document_agent.models import PresentationSlide
    from adaptive_document_agent.validation.claim_validator import ClaimValidator
    from .retained_analysis import findings
    linked = findings(result, allow_new_copy=True)
    failures = {}
    for decision in selection.decisions:
        if decision.decision != 'include':
            continue
        insight, primary, _ = linked[decision.insight_id]
        try:
            title, copy, ids = page_bindings(decision.page, insight, primary, context, result)
        except ValueError as exc:
            failures[insight.id] = [str(exc).removeprefix(f'{insight.id}: ')]
            continue
        probe = PresentationSlide(id=insight.id, slide_type='analysis', title=title, message=copy,
                                  observation_ids=sorted(ids))
        observations = [o for o in result.observations if o.id in ids]
        errors = ClaimValidator().validate_slide(probe, observations)
        if not errors:
            continue
        issues = failures[insight.id] = [e.message for e in errors]
        if any(e.code == 'direction_scope_ambiguous' for e in errors):
            periods = sorted({o.period for o in observations if o.id in primary and o.period})
            issues.append(f'Primary source periods are {periods}. In each directional clause, explicitly '
                'name the source metric and both source-supported endpoints for a comparison. '
                '"The decrease through [end]" supplies only one endpoint. Never infer the '
                'start from the earliest data. Separate the headline comparison from its drivers. '
                'If a driver has no source-supported interval, describe the supported event without '
                'claiming a change over an unspecified period. For a prose-only single-period driver, '
                'use attributed qualitative noun phrases with its original period and positive or '
                'negative role, without increase/decrease/higher/lower predicates or extra amounts.')
        if any(e.target_component == 'title' for e in errors):
            issues.append('Use a neutral metric/scope title, or explicitly write both '
                            'comparison endpoints in the title itself. Dates in the message do not '
                            'supply a missing title endpoint.')
    if failures:
        raise AuthoredPageErrors(failures)


def writer_context(context):
    """Use short references on the wire; persist only the original observation IDs."""
    rows = context['source_rows']
    aliases = {f'row-{i}': row['id'] for i, row in enumerate(rows, 1)}
    table_by_id = {row['id']: row['table_id'] for row in rows}
    findings = []
    for finding in context['findings']:
        primary = set(finding['observation_ids'])
        tables = {table_by_id[oid] for oid in primary if oid in table_by_id}
        allowed = [alias for alias, oid in aliases.items() if oid not in primary and table_by_id[oid] in tables]
        findings.append(dict(finding, allowed_companion_rows=allowed))
    return {**context, 'findings': findings, 'source_rows': [
        {**row, 'id': alias} for alias, row in zip(aliases, rows, strict=True)]}, aliases


def source_row_assurance(result, row_refs):
    """Expose explicit per-row source annotations on the wire only."""
    status = {o.id: o.audited_status for o in result.observations
              if o.audited_status in {'audited', 'unaudited'}}
    return {ref: status[oid] for ref, oid in row_refs.items() if oid in status}


def planned_source_citations(selection, context, result):
    """Expose the compiler's actual page references, never model-proposed citations."""
    from adaptive_document_agent.services.source_citations import evidence_pages, source_footer
    observations = {o.id: o for o in result.observations}
    insights = {i.id: i for i in result.insights}
    findings = {f['insight']['id']: f for f in context['findings']}
    available_pages = {p.page_number for p in result.document.pages}
    citations = []
    for decision in selection.decisions:
        if decision.decision != 'include':
            continue
        finding = findings.get(decision.insight_id, {})
        primary = set(finding.get('observation_ids', []))
        companions = set(decision.page.companion_ids if decision.page else [])
        ids = primary | companions
        if not primary or ids - observations.keys() or decision.insight_id not in insights:
            continue
        tables = {observations[k].effective_table_id for k in primary}
        allowed = {r['id'] for r in context.get('source_rows', []) if r['table_id'] in tables}
        if companions - primary - allowed:
            continue
        bound = [observations[k] for k in sorted(ids)]
        pages = evidence_pages(insights[decision.insight_id], bound, document=result.document)
        pages = sorted(set(pages) | context_evidence_pages(decision.page, context, result))
        if not pages or set(pages) - available_pages:
            continue
        citation = dict(insight_id=decision.insight_id, observation_ids=sorted(ids),
                        source_pages=pages, footer=source_footer(pages),
                        bound_periods=sorted({o.period for o in bound if o.period}))
        marked_tables = {o.effective_table_id for o in bound
                         if o.effective_table_id and o.audited_status in {'audited', 'unaudited'}}
        if marked_tables:
            citation['bound_assurance'] = [dict(observation_id=o.id, metric=o.metric_original,
                period=o.period, audited_status=o.audited_status)
                for o in bound if o.effective_table_id in marked_tables]
        citations.append(citation)
    return citations
