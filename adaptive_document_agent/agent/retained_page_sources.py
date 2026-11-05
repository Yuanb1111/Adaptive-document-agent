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
        description='Aim for under 900 characters using exact ISO dates and shared explicit units. '
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


def validate_authored_pages(selection, context, result):
    from adaptive_document_agent.models import PresentationSlide
    from adaptive_document_agent.validation.claim_validator import ClaimValidator
    from .retained_analysis import findings
    linked = findings(result, allow_new_copy=True)
    failures = []
    for decision in selection.decisions:
        if decision.decision != 'include':
            continue
        insight, primary, _ = linked[decision.insight_id]
        try:
            title, copy, ids = page_bindings(decision.page, insight, primary, context, result)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        probe = PresentationSlide(id=insight.id, slide_type='analysis', title=title, message=copy,
                                  observation_ids=sorted(ids))
        observations = [o for o in result.observations if o.id in ids]
        errors = ClaimValidator().validate_slide(probe, observations)
        failures.extend(f'{insight.id}: {e.message}' for e in errors)
        if any(e.code == 'direction_scope_ambiguous' for e in errors):
            periods = sorted({o.period for o in observations if o.id in primary and o.period})
            failures.append(f'{insight.id}: primary source periods are {periods}. For each comparison, '
                'including a source-attributed explanation, name its own start AND end in the same '
                'clause. "The decrease through [end]" supplies only one endpoint. Never infer the '
                'start from the earliest data. For nested comparisons, use separate sentences with '
                'one dated pair each. If the source does not specify a range for a driver, describe '
                'the supported dated event without claiming a change over an unspecified period.')
        if any(e.target_component == 'title' for e in errors):
            failures.append(f'{insight.id}: use a neutral metric/scope title, or explicitly write both '
                            'comparison endpoints in the title itself. Dates in the message do not '
                            'supply a missing title endpoint.')
    if failures:
        raise ValueError('\n'.join(failures))


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
        pages = evidence_pages(insights[decision.insight_id], [observations[k] for k in ids])
        if not pages or set(pages) - available_pages:
            continue
        citations.append(dict(insight_id=decision.insight_id, observation_ids=sorted(ids),
                              source_pages=pages, footer=source_footer(pages)))
    return citations
