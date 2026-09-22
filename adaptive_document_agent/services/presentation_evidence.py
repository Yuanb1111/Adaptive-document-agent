"""Bounded, scope-aware evidence retrieval for the semantic presentation planner.

Structural neighbours are retrieval hints, never proof of analytical relevance
or causality. The LLM selects themes; this module preserves facts and calculates
eligible single-series changes using the existing deterministic engine.
"""

from collections import defaultdict
from math import isfinite
import re

from adaptive_document_agent.document_model import metric_key, period_sort_key
from adaptive_document_agent.document_model.period_semantic_validator import classify_period
from adaptive_document_agent.models import Observation, PipelineResult
from adaptive_document_agent.utils.ids import stable_id
from .single_metric_analysis import single_metric_analysis

_META = {"table_context", "section", "column_role", "period_basis"}


def _subject_scope(o: Observation) -> tuple:
    dims = tuple(sorted((k, v) for k, v in {**o.dimensions, **o.category_dimensions}.items() if k not in _META))
    return metric_key(o), o.unit, o.currency, o.entity, dims, o.ifrs_status


def evidence_groups(observations: list[Observation]) -> list[list[Observation]]:
    """Keep metric scopes separate, including currencies, categories and basis.

Do not deduplicate cells here: conflicts must remain visible to validators.
"""
    groups = defaultdict(list)
    for o in observations:
        key = (*_subject_scope(o), o.period_basis, o.period_type, classify_period(o.period).period_type)
        groups[key].append(o)
    return [sorted(group, key=lambda o: (period_sort_key(o.period), o.id)) for _, group in sorted(groups.items(), key=lambda kv: str(kv[0]))]


def calculation_catalog(observations: list[Observation]) -> dict[str, dict]:
    """Derived claims with exact input IDs; no LLM arithmetic or invented units."""
    output = {}
    for group in evidence_groups(observations):
        if any(o.anomaly_notes or o.validation_status != "valid" for o in group):
            continue
        analysis = single_metric_analysis(group)
        if analysis is None:
            continue
        first = analysis.observations[0]

        def add(kind: str, value: float | None, items: list[Observation], unit: str):
            if value is None or not isfinite(value):
                return
            ids = [o.id for o in items]
            identifier = stable_id("presentation_calc", kind, *ids)
            suffix = "%" if unit == "percent" else " pp" if unit == "percentage_points" else ""
            output[identifier] = {
                "id": identifier, "kind": kind, "metric": first.metric_original,
                "value": value, "display": f"{value:,.1f}{suffix}", "unit": unit,
                "currency": first.currency if unit not in {"percent", "percentage_points"} else None,
                "periods": [o.period for o in items], "observation_ids": ids,
                "source_pages": sorted({e.page for o in items for e in o.evidence}),
                "fact_type": "calculated_result",
            }

        ends = [analysis.observations[0], analysis.observations[-1]]
        delta_unit = "percentage_points" if analysis.is_percentage else first.unit
        add("absolute_change", analysis.absolute_change, ends, delta_unit)
        add("percentage_change", analysis.percentage_change, ends, "percent")
        add("cagr", analysis.cagr, analysis.observations, "percent")
        for i, change in enumerate(analysis.changes):
            if change.is_yoy:
                pair = analysis.observations[i:i+2]
                add("yoy_absolute_change", change.absolute_change, pair, delta_unit)
                add("yoy_percentage_change", change.percentage_change, pair, "percent")
    return output


def observation_record(o: Observation) -> dict:
    return {"id": o.id, "metric": o.metric_canonical or o.metric_original,
            "metric_original": o.metric_original, "value": o.value, "raw_value": o.raw_value,
            "unit": o.unit, "raw_unit": o.raw_unit, "currency": o.currency, "period": o.period,
            "entity": o.entity, "dimensions": {**o.dimensions, **o.category_dimensions},
            "ifrs_status": o.ifrs_status, "period_basis": o.period_basis,
            "audited_status": o.audited_status, "parent_section": o.parent_section,
            "validation_status": o.validation_status, "confidence": o.confidence,
            "source_pages": sorted({e.page for e in o.evidence})}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]{2,}", text.casefold()))


def build_evidence_catalog(result: PipelineResult, *, max_series: int = 60, max_observations: int = 240) -> dict:
    """Retrieve whole small series fairly, guided by prior semantic-stage outputs.

Limits are explicit in the payload. Large series are omitted, not silently
sampled into a different trend. Existing chart data remain fully accessible in
their own bounded catalogue even when a series is outside the retrieval budget.
"""
    groups = evidence_groups(result.observations)
    chart_ids = {oid for c in result.charts for oid in [*c.observation_ids, *c.total_observation_ids]}
    queries = [result.profile.document_purpose, *result.profile.important_sections,
               *(s.title + " " + s.purpose for s in result.report_plan.sections),
               *(i.metric or i.title for i in sorted(result.insights, key=lambda i: -i.importance)[:12])]
    query_tokens = [_tokens(q) for q in queries if q]

    def relevance(group):
        text = " ".join(str(v or "") for o in group for v in
                        (o.metric_original, o.metric_canonical, o.source_section, o.entity, o.dimensions, o.category_dimensions))
        tokens = _tokens(text)
        return max((len(tokens & q) / max(len(q), 1) for q in query_tokens), default=0)

    ranked = sorted(groups, key=lambda g: (-relevance(g), -int(any(o.id in chart_ids for o in g)),
                                          -min(o.confidence for o in g), metric_key(g[0]), g[0].id))
    # First pass covers distinct metrics. One long category breakdown must not
    # crowd all other topics out simply because it has many rows.
    first, rest, seen = [], [], set()
    for group in ranked:
        key = metric_key(group[0])
        (rest if key in seen else first).append(group)
        seen.add(key)
    # Retrieve the separate period bases of already-selected subjects before a
    # long inventory of unrelated metrics consumes the entire budget. These
    # remain distinct series; retrieval never licenses an FY/interim comparison.
    chart_subjects = {_subject_scope(o) for o in result.observations if o.id in chart_ids}
    companions = [g for g in ranked if _subject_scope(g[0]) in chart_subjects]
    selected, count, selected_groups = [], 0, set()
    for group in [*companions, *first, *rest]:
        group_key = tuple(o.id for o in group)
        if group_key in selected_groups:
            continue
        if len(selected) >= max_series:
            break
        if len(group) + count > max_observations:
            continue
        selected.append(group)
        selected_groups.add(group_key)
        count += len(group)

    all_calculations = calculation_catalog(result.observations)
    bundles = []
    for group in selected:
        ids = {o.id for o in group}
        pages = sorted({e.page for o in group for e in o.evidence})
        identifier = stable_id("series_evidence", *sorted(ids))
        bundles.append({"id": identifier, "metric": group[0].metric_original,
            "observation_ids": [o.id for o in group], "periods": [o.period for o in group],
            "unit": group[0].unit, "currency": group[0].currency, "entity": group[0].entity,
            "dimensions": {**group[0].dimensions, **group[0].category_dimensions},
            "ifrs_status": group[0].ifrs_status, "period_basis": group[0].period_basis,
            "source_pages": pages, "source_sections": sorted({o.source_section for o in group if o.source_section}),
            "chart_ids": [c.id for c in result.charts if ids & set(c.observation_ids)],
            "calculation_ids": [cid for cid, c in all_calculations.items() if set(c["observation_ids"]) <= ids],
            "limitations": sorted({n for o in group for n in o.anomaly_notes}
                                   | {o.validation_status for o in group if o.validation_status != "valid"}
                                   | ({"missing value or source evidence"} if any(o.value is None or not o.evidence for o in group) else set()))})

    # Cross-page and cross-metric links expose structural affinity, not causation.
    for bundle in bundles:
        peers = []
        for other in bundles:
            if other["id"] == bundle["id"] or other["metric"] == bundle["metric"]:
                continue
            if other["entity"] != bundle["entity"]:
                continue
            periods = sorted(set(bundle["periods"]) & set(other["periods"]) - {None})
            sections = sorted(set(bundle["source_sections"]) & set(other["source_sections"]))
            if not periods:
                continue
            peers.append({"series_id": other["id"], "shared_periods": periods,
                          "same_definition_basis": other["ifrs_status"] == bundle["ifrs_status"],
                          "shared_sections": sections, "same_unit": other["unit"] == bundle["unit"] and other["currency"] == bundle["currency"],
                          "entity_confirmed": bool(bundle["entity"]),
                          "warning": "Structural retrieval hint only; justify relevance and verify scope before comparing."})
        bundle["related_evidence"] = sorted(peers, key=lambda p: (-len(p["shared_sections"]), -len(p["shared_periods"]), p["series_id"]))[:5]

    page_text = {p.page_number: p.text for p in result.document.pages}
    snippets_by_page = {}
    for group in selected:
        for o in group:
            for e in o.evidence:
                if e.page not in snippets_by_page and len(snippets_by_page) >= 12:
                    continue
                text = page_text.get(e.page) or e.text or ""
                if not text.strip():
                    continue
                # Retrieve around the actual row label, not always the page's
                # opening boilerplate. No document content is executed.
                position = text.casefold().find((e.row_label or o.metric_original).casefold())
                start = max(0, position - 220) if position >= 0 else 0
                existing = snippets_by_page.get(e.page)
                if existing is None or (position >= 0 and not existing[0]):
                    snippets_by_page[e.page] = (position >= 0, {"page": e.page, "text": text[start:start+2400],
                                               "anchor_observation_id": o.id})
    snippets = [s for _, s in snippets_by_page.values()]
    selected_ids = {o.id for g in selected for o in g} | chart_ids
    calculations = [c for c in all_calculations.values() if set(c["observation_ids"]) <= selected_ids]
    return {"series": bundles, "source_snippets": snippets,
            "observations": [observation_record(o) for g in selected for o in g],
            "calculations": calculations[:240], "omitted_series_count": len(groups) - len(selected),
            "total_series_count": len(groups), "retrieval_limits": {"series": max_series, "observations": max_observations, "source_pages": 12, "characters_per_source_page": 2400},
            "coverage_note": "This is a bounded evidence catalogue, not proof that omitted topics are absent from the document."}
