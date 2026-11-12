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
    'When a discussion has a literal dated window but does not separately date a related '
    'effect, distinguish those scopes explicitly: describe the effect within that named '
    'discussion and state that no separate comparison pair is supplied. Do not assign the '
    'window as new metric endpoints or discard the known discussion context. '
    'For source prose without eligible numeric rows, preserve the supported qualitative driver '
    'and the actual effect attributed by the source. An explicitly attributed qualitative '
    'explanation, supported by exact context_evidence, may say that a factor lengthened a '
    'cycle or shifted exposure without supplying new numeric endpoints. Do not invent a '
    'comparison interval when the source gives none; retain any literal timing qualifier. '
    'Keep the stated role without adding a favorable or adverse judgment the source '
    'does not make. Preserve a material composition shift toward or away from a source-defined '
    'category in attributed words, with its literal interval and exact supporting quotation. '
    'When that composition has no eligible numeric row, use the qualitative nominal form '
    '"The source describes a shift toward [category] during [literal source scope]" '
    '(or "away from" when supported). Do not recast it as "the share increased/decreased", '
    'which asserts a separate unbound measurement comparison. The source meaning and '
    'material adverse effect must remain; only its numerical-predicate framing changes. '
    'Do not replace that shift with a generic mention of adverse context. Numeric comparisons '
    'require bound rows and explicit endpoints; distinguish them from a literally supported '
    'source-attributed qualitative explanation. Do not turn prose-only factors into additional '
    'numerical trend claims. Do not require '
    'their unbound amounts on the analysis page. '
    'For a source-only trajectory without an eligible numeric series, retain a source-attributed '
    'qualitative shape, such as an initial dip followed by a rebound, rather than asserting '
    'an additional row-bound comparison for that unbound metric. Keep its literal scope and '
    'exact quotation; this does not authorize new amounts or calculated endpoints. '
    'A calculation definition may retain its literal day-count convention when complete '
    'context_evidence quotes the method and exact parameter phrases. Copy those phrases '
    'verbatim, such as [number] days for a given year or [number] days for a [duration]-month '
    'period. These are quoted method parameters, not additional measurements. Do not use '
    'them as amounts elsewhere or invent a calendar conversion. '
    'For material source-only qualifications without eligible rows, preserve their qualitative '
    'meaning, including adverse or limiting effects, and distinguish related gross/net or other '
    'populations. Do not require unbound percentages or thresholds. Do not present reassurance '
    'such as "relatively low" as an objective, population-wide conclusion. A source-attributed '
    'management judgment may remain alongside the material adverse shift and its exact '
    'source-defined scope, supported by literal context_evidence. Preserve those qualitative '
    'limits in the same discussion; neither the judgment nor the adverse shift substitutes '
    'for the other. Do not broaden a judgment about a subset. '
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
        description='Exact literal quotations from supplied source_pages, keyed by their supplied '
                    'physical page number, supporting qualitative '
                    'qualifications or drivers outside the primary row evidence. These do not '
                    'authorize additional amounts or companion rows. Complete literal calendar '
                    'dates in these quotations can support the dates of attributed source events. '
                    'Complete literal calculation definitions may bind their exact day-count parameters '
                    'in a method description, never an unrelated measurement.')


class ContextEvidenceError(ValueError):
    """A qualitative citation lacks a literal binding to its supplied page."""


def _context_sources(context, result):
    from adaptive_document_agent.services.source_quotes import normalize_quote
    allowed = {p['page'] for p in context.get('source_pages', [])}
    return {p.page_number: normalize_quote(p.text) for p in result.document.pages if p.page_number in allowed}


def rebind_context_evidence(selection, context, result):
    """Correct a page number only when the unchanged quote has one supplied match."""
    from adaptive_document_agent.services.source_quotes import normalize_quote
    sources = _context_sources(context, result)
    corrections = []
    for decision in selection.decisions:
        if decision.decision != 'include' or decision.page is None:
            continue
        for index, quote in enumerate(decision.page.context_evidence):
            text = normalize_quote(quote.text)
            if not text or text in sources.get(quote.page, ''):
                continue
            matches = [page for page, source in sources.items() if text in source]
            if len(matches) == 1:
                corrections.append(dict(insight_id=decision.insight_id, quote_index=index,
                                        original_page=quote.page, source_page=matches[0]))
                decision.page.context_evidence[index] = quote.model_copy(update={'page': matches[0]})
    return corrections


def context_evidence_pages(page, context, result):
    """Bind model-selected qualitative context without expanding numeric eligibility."""
    from adaptive_document_agent.services.source_quotes import normalize_quote
    if page is None or not page.context_evidence:
        return set()
    sources = _context_sources(context, result)
    pages = set()
    for index, quote in enumerate(page.context_evidence, 1):
        text = normalize_quote(quote.text)
        if not text or text not in sources.get(quote.page, ''):
            raise ContextEvidenceError('Context evidence must be a literal quote from a supplied source page. '
                f'Quote {index} does not bind to page {quote.page}. Copy a contiguous passage and its '
                'physical page number from the source_pages record, using its page field.')
        pages.add(quote.page)
    return pages


def retained_context_citations(result):
    """Recheck persisted quotation provenance for slide/theme validators."""
    from .retained_analysis import selected_record, selection_context, selection_input_matches, RetainedAnalysisSelection
    record = selected_record(result)
    if not record or not any(d.get('page', {}).get('context_evidence')
                            for d in record['selection']['decisions'] if d.get('page')):
        return {}
    context = selection_context(result)
    if not record.get('source_authoring') or not selection_input_matches(record, context, result):
        raise ValueError('Retained qualitative context has stale source bindings')
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    return {d.insight_id: context_evidence_pages(d.page, context, result)
            for d in selection.decisions if d.decision == 'include'}


def bound_authored_slide_ids(result, plan):
    """Recognize exact compiled model copy; this is never semantic approval.

    Generic chart-share retrieval cannot interpret source-only qualifications.
    Preserve this bound copy for the mandatory independent publication review.
    Numeric, literal-source and native presentation validation still apply.
    """
    from .retained_analysis import selected_record, selection_context, selection_input_matches, RetainedAnalysisSelection, findings
    record = selected_record(result)
    if not record or not record.get('source_authoring'):
        return set()
    context = selection_context(result)
    if not selection_input_matches(record, context, result):
        return set()
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    linked = findings(result, allow_new_copy=True)
    bound = {}
    for decision in selection.decisions:
        if decision.decision != 'include' or decision.page is None:
            continue
        insight, primary, _ = linked[decision.insight_id]
        bound[decision.insight_id] = page_bindings(decision.page, insight, primary, context, result)
    return {s.id for s in plan.slides if s.slide_type == 'analysis' and len(s.insight_ids) == 1
            and s.insight_ids[0] in bound
            and (s.title, s.message, set(s.observation_ids)) == bound[s.insight_ids[0]]}


def retained_context_dates(result, *, checked_citations=None):
    """Return only calendar identities from revalidated literal context quotes."""
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates
    return _retained_context_literals(result, literal_calendar_dates, checked_citations)


def retained_context_day_counts(result, *, checked_citations=None):
    """Return only literal parameters of revalidated calculation definitions."""
    from adaptive_document_agent.services.source_day_count import literal_day_count_conventions
    return _retained_context_literals(result, literal_day_count_conventions, checked_citations)


def _retained_context_literals(result, extract, checked_citations):
    from .retained_analysis import RetainedAnalysisSelection, selected_record
    checked = retained_context_citations(result) if checked_citations is None else checked_citations
    record = selected_record(result)
    if not checked or not record:
        return {}
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    return {d.insight_id: set().union(*(extract(q.text)
            for q in d.page.context_evidence if q.page in checked.get(d.insight_id, ())))
            for d in selection.decisions if d.decision == 'include' and d.page}


def page_sources(result, linked, *, include_neighbors=True):
    from adaptive_document_agent.services.source_citations import evidence_pages
    ids = set().union(*(entry[1] for entry in linked.values()))
    anchors = [o for o in result.observations if o.id in ids]
    pages = {e.page for o in anchors for e in o.evidence}
    for insight, _, _ in linked.values():
        pages.update(evidence_pages(insight, [], document=result.document))
    if include_neighbors:
        pages = {n for page in pages for n in (page - 1, page, page + 1)
                 if 1 <= n <= result.document.page_count}
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
    from adaptive_document_agent.services.calendar_claims import bound_period_dates, literal_calendar_dates
    from adaptive_document_agent.services.source_day_count import literal_day_count_conventions
    context_evidence_pages(page, context, result)
    context_dates = set().union(*(literal_calendar_dates(q.text) for q in page.context_evidence))
    day_counts = set().union(*(literal_day_count_conventions(q.text) for q in page.context_evidence))
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
    title, copy = (bound_period_dates(s, [*periods, *context_dates]) for s in (page.title, page.message))
    for field, text in [('title', title), ('message', copy)]:
        diagnostics = []
        if not _numeric_support(text, obs, diagnostics=diagnostics, context_dates=context_dates,
                                context_day_counts=day_counts):
            raise ValueError(f'{insight.id}.{field}: amount, date or rate outside its bound evidence: {text}. '
                f'Details: {diagnostics}. Exact quoted day-count parameters: {sorted(day_counts)}. '
                'For a day-count description, quote the complete method and copy its literal parameter '
                'phrases verbatim; this does not authorize other values. Bind any used table components to their exact '
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
                                  observation_ids=sorted(ids),
                                  source_pages=sorted(context_evidence_pages(decision.page, context, result)))
        observations = [o for o in result.observations if o.id in ids]
        errors = ClaimValidator().validate_slide(probe, observations)
        if not errors:
            continue
        issues = failures[insight.id] = [e.message for e in errors]
        if any(e.code == 'direction_scope_ambiguous' for e in errors):
            for error in errors:
                if error.code == 'direction_scope_ambiguous' and error.offending_direction:
                    issues.append(f'The exact rejected direction token is {error.offending_direction!r} '
                        f'in {error.target_component} at offsets {error.claim_start}:{error.claim_end}. '
                        'Correct this occurrence, including an attributive direction inside a driver '
                        'phrase; do not replace a different qualitative effect elsewhere in the clause.')
            periods = sorted({o.period for o in observations if o.id in primary and o.period})
            metrics = sorted({o.metric_original for o in observations})
            issues.append(f'Primary source periods are {periods}. In each directional clause, explicitly '
                'name the source metric and both source-supported endpoints for a comparison. '
                '"The decrease through [end]" supplies only one endpoint. Never infer the '
                'start from the earliest data. Separate the headline comparison from its drivers. '
                'If a driver has no source-supported interval, describe the supported event without '
                'claiming a change over an unspecified period. '
                f'Bound source metrics are {metrics}. Naming an unbound metric more explicitly '
                'cannot create a numeric comparison binding. For a prose-only trajectory, retain '
                'its source-attributed qualitative shape (for example an initial dip followed by '
                'a rebound), literal discussion scope and exact quotation, without new amounts '
                'or invented measurement endpoints. For a qualitative driver, preserve the '
                'actual source-attributed effect, not just a generic favorable/adverse label.')
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
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates
    from adaptive_document_agent.services.source_day_count import literal_day_count_conventions
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
        try:
            pages = sorted(set(pages) | context_evidence_pages(decision.page, context, result))
        except ContextEvidenceError:
            # A rejected draft has no publishable footer yet. Keep the other
            # findings reviewable so the writer can receive localized feedback.
            continue
        if not pages or set(pages) - available_pages:
            continue
        citation = dict(insight_id=decision.insight_id, observation_ids=sorted(ids),
                        source_pages=pages, footer=source_footer(pages),
                        bound_periods=sorted({o.period for o in bound if o.period}),
                        eligible_companion_rows=[r['id'] for r in context.get('source_rows', [])
                                                 if r['table_id'] in tables],
                        context_calendar_dates=sorted(set().union(*(literal_calendar_dates(q.text)
                            for q in decision.page.context_evidence))) if decision.page else [],
                        context_day_count_conventions=sorted(set().union(*(literal_day_count_conventions(q.text)
                            for q in decision.page.context_evidence))) if decision.page else [])
        marked_tables = {o.effective_table_id for o in bound
                         if o.effective_table_id and o.audited_status in {'audited', 'unaudited'}}
        if marked_tables:
            citation['bound_assurance'] = [dict(observation_id=o.id, metric=o.metric_original,
                period=o.period, audited_status=o.audited_status)
                for o in bound if o.effective_table_id in marked_tables]
        citations.append(citation)
    return citations
