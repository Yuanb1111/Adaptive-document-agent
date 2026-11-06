"""Bind source-authored analysis pages to their calculation and companion rows."""
from pydantic import BaseModel, ConfigDict, Field

from adaptive_document_agent.services.presentation_evidence import (
    ambiguous_source_table_ids, observation_uses_ambiguous_table)
from .audit_source_layout import audit_source_page


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


def page_sources(result, linked):
    ids = set().union(*(entry[1] for entry in linked.values()))
    anchors = [o for o in result.observations if o.id in ids]
    pages = {e.page for o in anchors for e in o.evidence}
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
    by_id = {o.id: o for o in result.observations}
    tables = {by_id[k].effective_table_id for k in primary}
    allowed = {r['id'] for r in context['source_rows'] if r['table_id'] in tables}
    ids = primary | set(page.companion_ids)
    foreign = set(page.companion_ids) - allowed - primary
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
                'name the source metric and both source-supported endpoints, including in attributed '
                'explanations. "The decrease through [end]" supplies only one endpoint. Never infer the '
                'start from the earliest data. Separate the headline comparison from its drivers. '
                'If a driver has no source-supported interval, describe the supported event without '
                'claiming a change over an unspecified period.')
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
        pages = evidence_pages(insights[decision.insight_id], bound)
        if not pages or set(pages) - available_pages:
            continue
        citation = dict(insight_id=decision.insight_id, observation_ids=sorted(ids),
                        source_pages=pages, footer=source_footer(pages))
        marked_tables = {o.effective_table_id for o in bound
                         if o.effective_table_id and o.audited_status in {'audited', 'unaudited'}}
        if marked_tables:
            citation['bound_assurance'] = [dict(observation_id=o.id, metric=o.metric_original,
                period=o.period, audited_status=o.audited_status)
                for o in bound if o.effective_table_id in marked_tables]
        citations.append(citation)
    return citations
