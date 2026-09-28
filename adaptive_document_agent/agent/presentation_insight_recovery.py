"""Reuse retained model-authored findings without repeating full slide planning."""

import json
import math
import re

from adaptive_document_agent.models import PresentationSlide, PresentationTheme, ValidationIssue
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from adaptive_document_agent.validation.presentation_provenance import insight_inputs


_GENERIC = re.compile(r"evidence.backed comparison|retained reported values|selected observations|"
                      r"supplied observations|paired observations exist|has observations for multiple periods", re.I)
_MONEY = re.compile(
    r"(?<!\w)(?P<currency>US\$|HK\$|S\$|RMB|CNY|CNH|USD|HKD|SGD|GBP|EUR|JPY|AUD|CAD|CHF|[$£€¥])?\s*"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(?P<scale>thousand|million|billion|bn|mn|[kmb])?(?!\w)", re.I)
_MONEY_SCALES = {"": 1, "k": 1_000, "thousand": 1_000, "m": 1_000_000,
                 "mn": 1_000_000, "million": 1_000_000, "b": 1_000_000_000,
                 "bn": 1_000_000_000, "billion": 1_000_000_000}
_PERCENT = re.compile(r"(?<!\w)(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
                      r"(?P<unit>percentage\s+points?|percent\s+points?|pp\b|%|percent(?:age)?\b)", re.I)


def _explicit_amounts_supported(text, observations, calculations):
    """Return grounded amount spans, or None when currency/scale is unsupported."""
    aliases = {"RMB": "CNY", "CNH": "CNY", "US$": "USD", "$": "USD", "HK$": "HKD",
               "S$": "SGD", "£": "GBP", "€": "EUR", "¥": "CNY"}
    currency_for = lambda value: aliases.get(str(value or "").upper(), str(value or "").upper())
    sources = [(float(o.value), currency_for(o.currency)) for o in observations
               if o.value is not None and o.currency]
    sources += [(c["value"], currency_for(c.get("currency"))) for c in calculations.values() if c.get("currency")]
    currencies = {currency for _, currency in sources}
    spans = []
    for match in _MONEY.finditer(text):
        if not match["currency"] and not match["scale"]:
            continue
        currency = currency_for(match["currency"])
        if not currency:
            # A bare scale has no permission to mix multiple currency scopes.
            if len(currencies) != 1:
                return None
            currency = next(iter(currencies))
        scale = _MONEY_SCALES[(match["scale"] or "").casefold()]
        literal = match["number"].replace(",", "")
        places = len(literal.split(".", 1)[1]) if "." in literal else 0
        claimed = abs(float(literal))
        if not any(curr == currency and (claimed != 0 or value == 0)
                   and math.isclose(round(abs(value) / scale, places), claimed,
                                                     rel_tol=1e-12, abs_tol=1e-9)
                   for value, curr in sources):
            return None
        spans.append(match.span())
    return spans


def _numeric_support(text, observations, computed_percentages=()):
    """Ground existing prose in source values and deterministic derived values.

    This does not write findings or infer relationships. Currency amounts can
    use conventional display scales; a percentage cannot borrow a currency
    amount. Direction is checked independently against the exact input series.
    """
    from adaptive_document_agent.services.presentation_evidence import calculation_catalog

    calculations = calculation_catalog(observations)
    spans = _explicit_amounts_supported(text, observations, calculations)
    if spans is None:
        return False
    reported_rates = [o.value for o in observations if o.value is not None
                      and (o.unit in {"percent", "%"} or o.unit_family == "percentage")]
    derived_rates = [c["value"] for c in calculations.values() if c["unit"] == "percent"] + list(computed_percentages)
    point_changes = [c["value"] for c in calculations.values() if c["unit"] == "percentage_points"]
    for match in _PERCENT.finditer(text):
        literal = match["number"].replace(",", "")
        places = len(literal.split(".", 1)[1]) if "." in literal else 0
        claimed = abs(float(literal))

        def matches(values):
            return any((claimed != 0 or value == 0) and math.isclose(round(abs(value), places), claimed,
                        rel_tol=1e-12, abs_tol=1e-9) for value in values)

        unit = match["unit"].casefold()
        if unit == "pp" or "point" in unit:
            if not matches(point_changes):
                return False
        elif not matches(reported_rates):
            # A computed growth rate is not a reported margin/ratio. Require
            # an explicit change predicate in this claim, never lend the rate
            # to a level statement such as "margin was 95.4%".
            prefix = re.split(r";|\n|(?<=[.!?])\s+", text[:match.start()])[-1]
            predicates = re.findall(
                r"\b(?:grew|growth|increased|decreased|rose|fell|declined|widened|narrowed|changed|was|were|reached|at)\b",
                prefix, re.I,
            )
            if not matches(derived_rates) or not predicates or predicates[-1].casefold() in {"was", "were", "reached", "at"}:
                return False
        spans.append(match.span())

    # Once typed amounts/rates have been checked, bare numbers may use exact
    # source values and periods only. No arbitrary display scale, derived rate
    # or rounding-to-zero is permitted to enter this untyped pool.
    source_numbers = set()
    for item in observations:
        source_numbers.update(PresentationPlanValidator._numbers(item.raw_value))
        source_numbers.update(re.findall(r"\d+", item.period or ""))
        if item.value is not None:
            source_numbers.add(str(item.value))
    masked = list(text)
    for start, end in spans:
        masked[start:end] = " " * (end - start)
    exact_values = {abs(float(token.rstrip("%"))) for token in source_numbers}
    for token in PresentationPlanValidator._numbers("".join(masked)):
        try:
            number = abs(float(token.rstrip("%")))
        except ValueError:
            return False
        if not any(math.isclose(number, allowed, rel_tol=1e-12, abs_tol=1e-9) for allowed in exact_values):
            return False
    return True


def _linked_findings(result):
    """Only task-provenanced, source-supported insights qualify for reuse."""
    refs = insight_inputs(result)
    by_id = {o.id: o for o in result.observations}
    tasks = {r.task_id: r for r in result.analysis_results}
    percentage_tasks = {t.id for t in result.analysis_plan
                        if t.tool_name in {"percentage_change", "growth_rate", "cagr", "contribution_share", "percentage_of_total"}}
    linked = []
    for insight in result.insights:
        ids = refs.get(insight.id, [])
        if (not ids or not insight.evidence or not insight.narrative.strip()
                or any(tid not in tasks or tasks[tid].result is None or not tasks[tid].evidence
                       or not tasks[tid].input_observation_ids
                       or any(oid not in by_id or not by_id[oid].evidence for oid in tasks[tid].input_observation_ids)
                       for tid in insight.result_ids)):
            continue
        observations = [by_id[oid] for oid in ids]
        if any(not o.evidence or o.value is None or o.validation_status not in {"valid", "partially_valid"}
               for o in observations):
            continue
        percentages = [tasks[tid].result for tid in insight.result_ids if tid in percentage_tasks
                       and isinstance(tasks[tid].result, (int, float))]
        # The model supplied both prose and a structured movement. A concise
        # movement often carries explicit comparison periods that a long prose
        # clause leaves implicit. Reuse it verbatim, never rewrite the direction.
        copies = [insight.narrative]
        if insight.movement:
            copies.append(f"{insight.title}: {insight.movement.rstrip('.')}.")
        for copy in copies:
            if (not _numeric_support(insight.title, observations, percentages)
                    or not _numeric_support(copy, observations, percentages)):
                continue
            probe = PresentationSlide(id="finding_check", slide_type="analysis", title=insight.title,
                                      message=copy, observation_ids=ids[:40])
            if not ClaimValidator().validate_slide(probe, observations):
                linked.append((insight, set(ids), copy))
                break
    return linked


def recover_insight_narrative(result, plan=None):
    """Mutate only generic analysis wording/evidence links; return changed IDs.

    With no explicit plan, updates ``result.presentation_plan``. Raw insights,
    observations, charts, usage and source records remain unchanged. All matching
    uses exact task input IDs, never metric words or shared PDF page numbers.
    Rejected candidate prose leaves the original slide intact. This is suitable
    for offline export of a cached repaired/fallback plan as well as new runs.
    """
    target = plan if plan is not None else result.presentation_plan
    if target is None or not any(s.slide_type == "analysis" and _GENERIC.search(s.message) for s in target.slides):
        return []
    findings = _linked_findings(result)
    charts = {c.id: c for c in result.charts}
    observations = {o.id: o for o in result.observations}
    insight_by_id = {i.id: i for i in result.insights}
    changed = []
    before = target.model_copy(deep=True)
    for slide in target.slides:
        if slide.slide_type != "analysis" or not _GENERIC.search(slide.message):
            continue
        chart_ids = list(dict.fromkeys([*slide.chart_ids, *(cid for b in slide.visual_blocks for cid in b.chart_ids)]))
        visible_ids = {*slide.observation_ids, *(oid for b in slide.visual_blocks for oid in b.observation_ids)}
        visible_ids.update(oid for cid in chart_ids if cid in charts
                           for oid in [*charts[cid].observation_ids, *charts[cid].total_observation_ids])
        candidates = [(item, ids, copy) for item, ids, copy in findings if ids <= visible_ids]
        candidates.sort(key=lambda pair: (-pair[0].importance, -pair[0].confidence))
        selected, covered = [], set()
        for item, ids, copy in candidates:
            if ids <= covered:
                continue
            selected.append((item, copy))
            covered.update(ids)
            if len(selected) == 3:
                break
        # Do not attach an explanation of one chart to unrelated companion charts.
        if not selected or any(not set(charts[cid].observation_ids) <= covered
                               for cid in chart_ids if cid in charts):
            continue
        slide.title = selected[0][0].title
        slide.message = selected[0][1]
        # Explicit copies prevent renderers from replacing an empty bullet list
        # with the unvalidated long-form insight narrative. Duplicate message
        # copy is removed by the compositor, not by consulting raw insight prose.
        slide.bullets = [copy for item, copy in selected]
        slide.bullet_observation_ids = []
        slide.insight_ids = [item.id for item, copy in selected]
        # A structured movement may mention a signed delta as a positive
        # magnitude ("declined 1.3 pp"). Bind that exact Python calculation,
        # rather than treating the model's own prose as its numeric evidence.
        from adaptive_document_agent.services.presentation_evidence import calculation_catalog
        catalog = calculation_catalog([observations[oid] for oid in visible_ids if oid in observations])
        source_parts = [str(value) for oid in visible_ids if oid in observations
                        for value in (observations[oid].value, observations[oid].raw_value, observations[oid].period)]
        source_parts += [text for item, copy in selected for text in (item.title, item.narrative)]
        allowed = set().union(*(PresentationPlanValidator._numbers(part) for part in source_parts))
        missing = PresentationPlanValidator._numbers(" ".join([slide.message, *slide.bullets])) - allowed
        for cid, calc in catalog.items():
            tokens = PresentationPlanValidator._numbers(str(calc["value"]) + "; " + calc["display"])
            magnitudes = {token.lstrip("-") for token in tokens}
            if missing & (tokens | magnitudes) and cid not in slide.calculation_ids:
                slide.calculation_ids.append(cid)
        slide.source_pages = sorted({e.page for oid in visible_ids if oid in observations
                                     for e in observations[oid].evidence}
                                    | {e.page for item, copy in selected for e in item.evidence})
        changed.append(slide.id)

    if not changed:
        return []
    # A fully recovered chart selection already encodes model-chosen subjects.
    # Bind one evidence boundary per retained page; do not invent cross-metric
    # relationships or force incompatible periods onto a combined chart.
    analysis = [s for s in target.slides if s.slide_type == "analysis"]
    if not target.themes and all(s.id in changed for s in analysis):
        for slide in analysis:
            chart_ids = list(dict.fromkeys([*slide.chart_ids, *(c for b in slide.visual_blocks for c in b.chart_ids)]))
            ids = {*slide.observation_ids, *(o for b in slide.visual_blocks for o in b.observation_ids)}
            ids.update(o for cid in chart_ids for o in [*charts[cid].observation_ids, *charts[cid].total_observation_ids])
            question = next((charts[cid].question for cid in chart_ids if charts[cid].question), slide.title)
            slide.theme_id = f"retained_{slide.id}"
            slide.analytical_question = question
            # Keep the complete original wording, including any caveat, on the
            # theme and in retained insights even when a shorter movement is shown.
            rationale = insight_by_id[slide.insight_ids[0]].narrative
            slide.selection_reason = rationale
            target.themes.append(PresentationTheme(
                id=slide.theme_id, title=slide.title, question=question, rationale=rationale,
                chart_ids=chart_ids, observation_ids=sorted(ids), insight_ids=slide.insight_ids,
                source_pages=slide.source_pages,
            ))
    try:
        PresentationPlanValidator().validate(target, result)
    except ValueError as exc:
        target.slides, target.themes = before.slides, before.themes
        result.validation_warnings.append(ValidationIssue(
            code="presentation_insight_recovery_rejected", stage="presentation", severity="warning",
            related_ids=changed, message=str(exc),
        ))
        return []
    from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review
    stamp_editorial_review(target, result, origin="repaired")
    result.validation_warnings.append(ValidationIssue(
        code="presentation_insight_recovery", stage="presentation", severity="info", related_ids=changed,
        message=json.dumps({"reason": "Reused source-validated model findings for the same chart inputs",
            "original_slides": [s.model_dump(mode="json") for s in before.slides if s.id in changed]}, ensure_ascii=False),
    ))
    return changed


def plan_from_retained_insights(result):
    """Avoid a second paid planning pipeline after topic selection has failed."""
    from .presentation_plan_recovery import PresentationPlanRecovery
    from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review

    plan = PresentationPlanRecovery().fallback(result, validate=False)
    changed = recover_insight_narrative(result, plan)
    PresentationPlanValidator().validate(plan, result)
    if not changed:
        stamp_editorial_review(plan, result, origin="fallback")
    return plan
