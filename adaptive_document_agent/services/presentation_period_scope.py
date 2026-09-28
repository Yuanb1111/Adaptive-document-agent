"""Constrain broad period wording to the source periods actually displayed.

This is an evidence-bound copy edit, not a new analytical interpretation. It
does not infer a direction, calculate a movement, or combine annual/interim data.
"""

from __future__ import annotations

from collections import defaultdict
import json
import re

from adaptive_document_agent.models import Observation, PipelineResult, PresentationPlan, ValidationIssue
from .presentation_evidence import ambiguous_source_table_ids, observation_uses_ambiguous_table

_BROAD = re.compile(
    r"\b(?:over|across|during|throughout|for|in)\s+(?:the\s+)?"
    r"(?:(?:whole|entire|full)\s+)?"
    r"(?:track[ -]record\s+period|(?:whole|entire|full)\s+(?:reporting\s+)?period|reporting\s+period)\b",
    re.I,
)
_META = {"column_role", "table_context", "section", "period_basis"}


def _subject(item: Observation) -> tuple | None:
    """An exact source row, never a same-page or fuzzy-metric association."""
    rows = {e.row_label.strip().casefold() for e in item.evidence if e.row_label and e.row_label.strip()}
    if not item.effective_table_id or len(rows) != 1:
        return None
    dims = tuple(sorted((k, v) for k, v in {**item.dimensions, **item.category_dimensions}.items() if k not in _META))
    return (item.effective_table_id, tuple(rows), item.metric_original.casefold(), item.unit,
            item.unit_scale, item.currency, item.entity, item.ifrs_status, dims)


def _period(item: Observation) -> tuple[str, str] | None:
    """Accept explicit, unambiguous labels only; never turn an unknown year into FY."""
    label = re.sub(r"\s+", "", item.period or "").rstrip("*").upper()
    if re.fullmatch(r"(?:FY)?(?:19|20)\d{2}", label):
        if (not label.startswith("FY") and item.period_basis.upper() != "FY"
                and item.period_type != "fiscal_year"):
            return None
        family = "FY"
        label = "FY" + label.removeprefix("FY")
        if item.period_type not in {"generic", "fiscal_year"}:
            return None
    elif match := re.fullmatch(r"(\d{1,2}M)((?:19|20)\d{2})", label):
        family = match[1]
        if not 1 <= int(family[:-1]) <= 12 or item.period_type not in {"generic", "interim_flow", "interim_period"}:
            return None
    elif match := re.fullmatch(r"(Q[1-4]|H[12]|[12]H|[1-4]Q|YTD)((?:19|20)\d{2})", label):
        family = match[1]
        if item.period_type not in {"generic", "quarter", "interim_flow", "interim_period", "ytd"}:
            return None
    else:
        return None
    basis = item.period_basis.upper()
    expected = "6M" if "H" in family else "3M" if "Q" in family else family
    if basis not in {"", "GENERIC", expected}:
        return None
    # Explicit dates distinguish, for example, six months ending June vs December.
    dates = tuple((value or "")[4:] for value in (item.period_start, item.period_end))
    return family + repr(dates), label


def _period_text(labels: set[str]) -> str:
    ordered = sorted(labels, key=lambda value: (int(re.search(r"\d{4}$", value)[0]), value))
    # A range implies all intervening years. Keep gaps explicit.
    years = [int(value[-4:]) for value in ordered]
    prefixes = {value[:-4] for value in ordered}
    if len(ordered) > 2 and len(prefixes) == 1 and years == list(range(years[0], years[-1] + 1)):
        return f"{ordered[0]}–{ordered[-1]}"
    return " and ".join(ordered) if len(ordered) < 3 else ", ".join(ordered)


def _visible_groups(slide, charts, observations) -> list[tuple[str, list[Observation]]]:
    groups = []
    chart_ids = list(dict.fromkeys([*slide.chart_ids, *(cid for block in slide.visual_blocks for cid in block.chart_ids)]))
    for cid in chart_ids:
        chart = charts.get(cid)
        if chart is None or any(oid not in observations for oid in chart.observation_ids):
            return []
        groups.append((chart.title, [observations[oid] for oid in chart.observation_ids]))
    for block in slide.visual_blocks:
        if block.role in {"kpi", "table"}:
            if any(oid not in observations for oid in block.observation_ids):
                return []
            groups.append((block.title or slide.section_title, [observations[oid] for oid in block.observation_ids]))
    return groups


def _evidence_context(result):
    observations = {o.id: o for o in result.observations}
    charts = {c.id: c for c in result.charts}
    ambiguous = ambiguous_source_table_ids(result)
    eligible = {o.id for o in result.observations if o.value is not None and o.evidence
                and o.validation_status == "valid" and not o.anomaly_notes
                and not observation_uses_ambiguous_table(o, ambiguous)}
    by_subject = defaultdict(list)
    for item in result.observations:
        if (key := _subject(item)) is not None:
            by_subject[key].append(item)
    return observations, charts, eligible, by_subject


def _companion_records(visible, by_subject, eligible):
    companions = {}
    for anchor in visible:
        displayed = {_period(o) for o in visible if _subject(o) == _subject(anchor)}
        for item in by_subject.get(_subject(anchor), []):
            if item.id in eligible and (period := _period(item)) is not None and period not in displayed:
                companions[item.id] = item
    return companions


def review_presentation_period_scope(result, plan=None) -> list[tuple[str, str]]:
    """Read current copy/evidence; historical audits never force a review flag.

    Return ``(slide_id, reason)`` for still-unresolved scope. A later corrected
    copy or complete compatible evidence clears the issue without deleting audit.
    """
    target = plan or result.presentation_plan
    if target is None:
        return []
    candidates = [s for s in target.slides if s.slide_type == "analysis" and any(
        _BROAD.search(text) or "the respective displayed periods" in text.casefold()
        for text in [s.title, s.message, *s.bullets])]
    if not candidates:
        return []
    observations, charts, eligible, by_subject = _evidence_context(result)
    findings = []
    for slide in candidates:
        groups = _visible_groups(slide, charts, observations)
        visible = list({o.id: o for _, items in groups for o in items}.values())
        scopes = [{_period(o) for o in items} for _, items in groups]
        if (not groups or any(not scope or None in scope for scope in scopes)
                or any(o.id not in eligible for o in visible)):
            findings.append((slide.id, "Displayed period scope is unknown, missing or ineligible; broad-period copy requires review."))
        elif not (all(scope == scopes[0] for scope in scopes) and len({p[0] for p in scopes[0]}) == 1):
            findings.append((slide.id, "Displayed panels use different period sets; the combined claim requires review."))
        elif len(set(slide.observation_ids) | _companion_records(visible, by_subject, eligible).keys()) > 40:
            findings.append((slide.id, "Additional period evidence exceeds the slide reference limit; requires a separate evidence panel."))
    return findings


def _add_audit(result, slide, payload, *, unresolved=False):
    message = json.dumps({"slide_id": slide.id, **payload}, ensure_ascii=False, sort_keys=True)
    code = "presentation_period_scope_unresolved" if unresolved else "presentation_period_scope"
    if not any(issue.code == code and issue.message == message for issue in result.validation_warnings):
        by_id = {o.id: o for o in result.observations}
        ids = list(dict.fromkeys(payload.get("visible_observation_ids", []) + payload.get("additional_observation_ids", [])))
        result.validation_warnings.append(ValidationIssue(
            code=code, stage="presentation", severity="warning" if unresolved else "info",
            message=message, related_ids=[slide.id, *ids],
            evidence=[e for oid in ids if oid in by_id for e in by_id[oid].evidence],
        ))


def _require_review(plan, note):
    if note not in plan.editorial_notes:
        plan.editorial_notes.append(note)
    if plan.editorial_status != "degraded":
        plan.editorial_status = "needs_review"


def _sync_summary_copies(result, plan):
    """Propagate only exact copies of an existing, still-current scoped claim.

    Audit mappings also cover a summary rebuilt from cached model topics on a
    later prepare pass. Conflicting mappings never choose one slide's scope.
    """
    by_id = {slide.id: slide for slide in plan.slides if slide.slide_type == "analysis"}
    replacements = defaultdict(set)
    for issue in result.validation_warnings:
        if issue.code != "presentation_period_scope":
            continue
        try:
            audit = json.loads(issue.message)
        except (ValueError, TypeError):
            continue
        slide = by_id.get(audit.get("slide_id"))
        if slide is None:
            continue
        original, current = audit.get("original", {}), audit.get("replacement", {})
        for field in ("title", "message"):
            old, new = original.get(field), current.get(field)
            if old and new and old != new and getattr(slide, field) == new:
                replacements[old].add(new)
        for old, new in zip(original.get("bullets", []), current.get("bullets", [])):
            if old and new and old != new and new in slide.bullets:
                replacements[old].add(new)
    unique = {old: next(iter(values)) for old, values in replacements.items() if len(values) == 1}
    changed = []
    for slide in plan.slides:
        if slide.slide_type != "executive_summary":
            continue
        original = {"title": slide.title, "message": slide.message, "bullets": list(slide.bullets)}
        slide.title = unique.get(slide.title, slide.title)
        slide.message = unique.get(slide.message, slide.message)
        slide.bullets = [unique.get(text, text) for text in slide.bullets]
        updated = {"title": slide.title, "message": slide.message, "bullets": list(slide.bullets)}
        if updated != original:
            _add_audit(result, slide, {"original": original, "replacement": updated,
                "visible_observation_ids": list(slide.observation_ids), "reason": "exact summary copy of a scoped analytical claim"})
            changed.append(slide.id)
    return changed


def prepare_presentation_period_scope(result: PipelineResult, plan: PresentationPlan | None = None) -> list[str]:
    """Mutate presentation copy/audit only; return changed slide IDs.

    Only broad period phrases are eligible. Exact chart periods are preserved;
    unknown or mixed scope is flagged, never replaced with a guessed calendar.
    Additional periods come from the identical source row and remain separate
    coverage references, not new chart data or newly authored trend conclusions.
    """
    target = plan or result.presentation_plan
    if target is None:
        return []
    candidates = [s for s in target.slides if s.slide_type == "analysis" and any(
        _BROAD.search(text) for text in [s.title, s.message, *s.bullets])]
    if not candidates:
        return _sync_summary_copies(result, target)
    observations, charts, eligible, by_subject = _evidence_context(result)
    changed = []
    for slide in candidates:
        groups = _visible_groups(slide, charts, observations)
        visible = list({o.id: o for _, items in groups for o in items}.values())
        ids = [o.id for o in visible]
        original = {"title": slide.title, "message": slide.message, "bullets": list(slide.bullets)}
        scopes = [{_period(o) for o in items} for _, items in groups]
        if (not groups or any(not scope or None in scope for scope in scopes)
                or any(o.id not in eligible for o in visible)):
            note = f"Slide {slide.id}: displayed period scope could not be verified; broad-period copy requires review."
            _require_review(target, note)
            _add_audit(result, slide, {"original": original, "visible_observation_ids": ids,
                                     "reason": "unknown, missing or ineligible displayed period evidence"}, unresolved=True)
            continue
        same_scope = all(scope == scopes[0] for scope in scopes) and len({p[0] for p in scopes[0]}) == 1
        # Find a period outside the actual displayed scope for the same source row.
        companions = _companion_records(visible, by_subject, eligible)
        if same_scope and not companions:
            continue  # The full known series is already shown; no narrowing needed.
        if len(set(slide.observation_ids) | companions.keys()) > 40:
            note = f"Slide {slide.id}: additional period evidence exceeds the slide reference limit; requires a separate evidence panel."
            _require_review(target, note)
            _add_audit(result, slide, {"original": original, "visible_observation_ids": ids,
                "additional_observation_ids": list(companions), "reason": "reference capacity exceeded"}, unresolved=True)
            continue
        label = _period_text({p[1] for p in scopes[0]}) if same_scope else "the respective displayed periods"
        replacement = "over " + label
        slide.title = _BROAD.sub(replacement, slide.title)
        slide.message = _BROAD.sub(replacement, slide.message)
        slide.bullets = [_BROAD.sub(replacement, text) for text in slide.bullets]
        details = []
        if not same_scope:
            details.append("Displayed periods: " + "; ".join(
                f"{name}: {_period_text({p[1] for p in scope})}" for (name, _), scope in zip(groups, scopes)) + ".")
            _require_review(target, f"Slide {slide.id}: displayed panels use different period sets; the combined claim requires review.")
        if companions:
            separate = defaultdict(list)
            for item in companions.values():
                separate[_period(item)[0]].append(item)
            for items in separate.values():
                periods = _period_text({_period(o)[1] for o in items})
                details.append(f"Separate source coverage: {periods}; outside the displayed comparison (see source pages).")
        coverage = " ".join(details)
        if coverage:
            if len(slide.bullets) < 5:
                slide.bullets.append(coverage)
                while len(slide.bullet_observation_ids) < len(slide.bullets) - 1:
                    slide.bullet_observation_ids.append([])
                slide.bullet_observation_ids.append(list(companions) or ids)
            else:
                slide.bullets[-1] += " " + coverage
                while len(slide.bullet_observation_ids) < len(slide.bullets):
                    slide.bullet_observation_ids.append([])
                slide.bullet_observation_ids[-1] = list(dict.fromkeys([*slide.bullet_observation_ids[-1], *companions]))
            # Reference IDs establish provenance only; two_up/auto composition
            # does not add raw rows to the selected chart series.
            slide.observation_ids = list(dict.fromkeys([*slide.observation_ids, *companions]))
            slide.source_pages = sorted(set(slide.source_pages) | {e.page for o in companions.values() for e in o.evidence})
            theme = next((t for t in target.themes if t.id == slide.theme_id), None)
            if theme:
                theme.observation_ids = list(dict.fromkeys([*theme.observation_ids, *companions]))
                theme.source_pages = sorted(set(theme.source_pages) | set(slide.source_pages))
        note = f"Slide {slide.id}: broad period wording restricted to {label}; additional periods remain separate evidence."
        if note not in target.editorial_notes:
            target.editorial_notes.append(note)
        _add_audit(result, slide, {"original": original,
            "replacement": {"title": slide.title, "message": slide.message, "bullets": slide.bullets},
            "visible_observation_ids": ids, "additional_observation_ids": list(companions),
            "coverage_note": coverage, "different_displayed_period_sets": not same_scope})
        changed.append(slide.id)
    return [*changed, *_sync_summary_copies(result, target)]
