"""Bind comparative presentation wording to visible, source-aligned records.

The model chooses the subject and claim. This layer only retrieves the same
table's reported shares, checks a complete denominator, and narrows unsupported
claims. It never modifies extracted records or computes an invented share.
"""

from __future__ import annotations

from collections import defaultdict
from math import isclose, isfinite
import re

from adaptive_document_agent.document_model import period_sort_key
from adaptive_document_agent.models import ChartPlan, PipelineResult, PresentationPlan, PresentationVisualBlock
from adaptive_document_agent.utils.ids import stable_id
from adaptive_document_agent.validation.narrative_plan_validator import expanded_observation_ids
from .presentation_evidence import ambiguous_source_table_ids, observation_uses_ambiguous_table
from .presentation_identity import reconcile_presentation_identity
from .presentation_share_claims import (
    SHARE_WORD as _SHARE, source_row as _row,
    row_position as _position, reported_denominator, share_claims,
    share_direction_supported, source_total_denominators, denominator_matches,
)

_RANK = re.compile(r"\b(largest|smallest|highest|lowest)\b", re.I)
_META = {"column_role", "table_context", "section", "period_basis"}
_NARROW_REASON = "The retained records support these reported values; the broader comparison was omitted."


def visible_observation_ids(slide, charts):
    """Visible measures exclude provenance-only references for other periods."""
    chart_ids = [*slide.chart_ids, *(cid for block in slide.visual_blocks for cid in block.chart_ids)]
    return list(dict.fromkeys([
        *(oid for cid in chart_ids if cid in charts for oid in charts[cid].observation_ids),
        *(oid for block in slide.visual_blocks if block.role in {"table", "kpi", "waterfall", "matrix", "horizon"} for oid in block.observation_ids),
    ]))


def _scope(item):
    return (item.effective_table_id, item.entity, item.period_basis, item.period_type,
            item.ifrs_status, tuple(sorted((k, v) for k, v in {**item.dimensions, **item.category_dimensions}.items()
                                          if k not in _META)))


def _share(item):
    # ratio_share also covers expense/revenue and other unrelated denominators.
    # Even a coincidental sum of 100 cannot establish a common population.
    return reported_denominator(item) == "total"


def _unique_periods(items, periods):
    by_period = defaultdict(list)
    for item in items:
        if item.period in periods:
            by_period[item.period].append(item)
    if set(by_period) != periods:
        return []
    output = []
    for period in sorted(periods, key=period_sort_key):
        peers = by_period[period]
        if len({(item.value, item.raw_value, item.audited_status) for item in peers}) != 1:
            return []
        output.append(min(peers, key=lambda item: item.id))
    return output


def _claim_subject(selected, text, *, ranking=False):
    """Resolve only an explicit unique row or the immediately preceding 'its' subject."""
    pattern = _RANK if ranking else _SHARE
    clauses = re.split(r"[,;.!?]|\bwhile\b|\bwhereas\b", text, flags=re.I)
    subjects = set()
    for i, clause in enumerate(clauses):
        if not pattern.search(clause):
            continue
        matching = {_row(item) for item in selected if _position(item, clause) >= 0}
        if not matching and i and re.search(r"(?i)\bits\b", clause):
            matching = {_row(item) for item in selected if _position(item, clauses[i - 1]) >= 0}
        if len(matching) != 1:
            return ""
        subjects.update(matching)
    return next(iter(subjects)) if len(subjects) == 1 else ""


def _reported_shares(selected, eligible, text, *, ranking=False, subject=None, denominator="", totals=None):
    """Require the selected row, source table and periods, rather than label similarity."""
    subject = subject or _claim_subject(selected, text, ranking=ranking)
    anchors = sorted((item for item in selected if item.effective_table_id and _row(item) == subject),
                     key=lambda item: (not _share(item), item.id)) if subject else []
    for anchor in anchors:
        periods = {item.period for item in selected if item.period and _scope(item) == _scope(anchor)
                   and _row(item) == _row(anchor)}
        if len(periods) < 2:
            continue
        matches = [item for item in eligible if reported_denominator(item)
                   and _scope(item) == _scope(anchor) and _row(item) == _row(anchor)]
        wanted = "total" if ranking else denominator
        denominators = {reported_denominator(item) for item in matches}
        if not wanted:
            # A bare share can use a unique reported denominator; it cannot
            # choose between percentages of revenue, units or another total.
            if len(denominators) != 1:
                continue
            wanted = next(iter(denominators))
        matches = [item for item in matches if denominator_matches(item, wanted, totals or {})]
        shares = _unique_periods(matches, periods)
        if shares:
            return shares
    return []


def _ranking_peers(shares, eligible, text):
    first = shares[0]
    columns = {e.column_label for item in shares for e in item.evidence if e.column_label}
    if len(columns) != 1:
        return []
    periods = {item.period for item in shares}
    rows = defaultdict(list)
    for item in eligible:
        if (not _share(item) or _scope(item) != _scope(first) or not _row(item)
                or {e.column_label for e in item.evidence if e.column_label} != columns
                or not 0 <= float(item.value) <= 100):
            continue
        if re.match(r"(?i)^(?:grand\s+total|sub[ -]?total|total|aggregate)\b", _row(item)):
            continue
        rows[_row(item)].append(item)
    groups = [_unique_periods(items, periods) for items in rows.values()]
    if not 2 <= len(groups) <= 6 or any(not group for group in groups):
        return []
    # A few selected competitors cannot establish the maximum of the whole.
    if any(not isclose(sum(float(group[i].value) for group in groups), 100, abs_tol=.5)
           for i in range(len(shares))):
        return []
    rank = _RANK.search(text).group(1).casefold()
    extreme = min if rank in {"smallest", "lowest"} else max
    latest = len(shares) - 1
    if float(shares[latest].value) != extreme(float(group[latest].value) for group in groups):
        return []
    if re.search(r"(?i)\b(?:became|become)\b", text):
        if float(shares[0].value) == extreme(float(group[0].value) for group in groups):
            return []
    return [item for group in groups for item in group]


def _narrow(slide, replacements):
    old = slide.title
    old_message = slide.message
    title = slide.section_title.strip()
    if title and (_RANK.search(title) or _SHARE.search(title)):
        # A selected topic can name several measures even when one comparative
        # claim cannot be bound. Keep the independently named measures visible.
        parts = [re.sub(r"(?i)^and\s+", "", part.strip()) for part in title.split(",")]
        safe = [part for part in parts if part and not (_RANK.search(part) or _SHARE.search(part))
                and re.search(r"[A-Za-z]{3,}", re.sub(
                    r"(?i)\b(?:FY|[1369]M|[12]H|Q[1-4])?\s*(?:19|20)\d{2}\b", "", part))]
        title = " and ".join(safe) if safe else ""
    slide.title = title or "Reported measures"
    if _RANK.search(slide.message) or _SHARE.search(slide.message):
        # Keep independent qualifications even when the comparative sentence
        # has to go. Raw semantic decisions remain in presentation_topics.
        clauses = re.split(r"(?<=[.!?])\s+|;\s*", slide.message)
        retained = [part for part in clauses if not (_RANK.search(part) or _SHARE.search(part))]
        slide.message = " ".join(retained).strip() or (
            f"Reported values for {slide.title} across the cited periods."
            if title else "Reported values across the cited periods."
        )
    elif slide.message == "Reported values across the cited periods." and title:
        # Cached plans may already contain the previous generic fallback.
        slide.message = f"Reported values for {title} across the cited periods."
    slide.analytical_question = "How do the reported values vary across the cited periods?"
    slide.selection_reason = _NARROW_REASON
    replacements[old] = slide.title
    if old_message and old_message != slide.message:
        replacements[old_message] = slide.message


def prepare_presentation_claims(result: PipelineResult, plan: PresentationPlan | None = None) -> list[str]:
    """Reconcile newly compiled or cached plans without additional model requests."""
    plan = plan or result.presentation_plan
    if plan is None:
        return []
    from .presentation_audit_scope import reconcile_audit_scope
    reconcile_audit_scope(result, plan)
    from adaptive_document_agent.agent.presentation_closing_validation import withhold_cached_closing_claims
    closing_notes = withhold_cached_closing_claims(result, plan)
    from adaptive_document_agent.agent.presentation_insight_recovery import recover_insight_narrative
    recover_insight_narrative(result, plan)
    if plan.planning_origin in {"topic_compilation", "topic_recovery"}:
        from adaptive_document_agent.agent.presentation_summary_selection import rebuild_selected_topic_summary
        rebuild_selected_topic_summary(result, plan)
    reconcile_presentation_identity(plan, result)
    from .composition_preservation import restore_selected_compositions, reconcile_composition_coverage
    composition_notes = restore_selected_compositions(result, plan)
    ambiguous = ambiguous_source_table_ids(result)
    eligible = [item for item in result.observations if item.value is not None and isfinite(item.value)
                and item.period and item.evidence and item.validation_status == "valid" and not item.anomaly_notes
                and not observation_uses_ambiguous_table(item, ambiguous)]
    by_id = {item.id: item for item in result.observations}
    charts = {chart.id: chart for chart in result.charts}
    themes = {theme.id: theme for theme in plan.themes}
    topics = {topic.id: topic for topic in result.presentation_topics.topics} if result.presentation_topics else {}
    from adaptive_document_agent.agent.presentation_topic_scope_recovery import withheld_topic_ids
    withheld = withheld_topic_ids(plan)
    totals = source_total_denominators(result)
    from .presentation_ratio_definitions import ratio_definitions, source_defined_possessive_share
    definitions = ratio_definitions(result)
    notes, replacements, restored_titles = [*closing_notes, *composition_notes], {}, defaultdict(set)
    for slide in plan.slides:
        if slide.slide_type != "analysis":
            continue
        # Cached plans may have been narrowed by the old one-subject / Total-only
        # check. Reconsider only that exact repair, using the retained model claim
        # and all current evidence checks. Never reset other repaired wording.
        restoring = (topics.get(slide.theme_id) if slide.selection_reason == _NARROW_REASON
                     and slide.theme_id not in withheld else None)
        narrowed_title = slide.title
        if restoring and (_SHARE.search(restoring.takeaway) or _RANK.search(restoring.takeaway)):
            slide.title = restoring.takeaway
        else:
            restoring = None
        text = slide.title + " " + slide.message
        if not (_RANK.search(text) or _SHARE.search(text)):
            continue
        ids = expanded_observation_ids(slide, charts)
        selected = [by_id[oid] for oid in ids if oid in by_id]
        displayed = [by_id[oid] for oid in visible_observation_ids(slide, charts) if oid in by_id]
        ranking = bool(_RANK.search(text))
        clauses = [share_claims(selected, copy) for copy in (slide.title, slide.message)]
        theme = themes.get(slide.theme_id)
        qualifications = [slide.message, *(theme.caveats if theme else [])]
        shares = []
        for index, copy in enumerate((slide.title, slide.message)):
            if clauses[index] is None:
                sourced = source_defined_possessive_share(copy, selected, displayed, eligible, definitions)
                if sourced:
                    clauses[index] = []
                    shares.extend(sourced)
        unsupported = any(group is None for group in clauses)
        for claim in [claim for group in clauses if group is not None for claim in group]:
            scoped = displayed if any(_row(item) == claim.subject for item in displayed) else selected
            bound = _reported_shares(scoped, eligible, claim.text, subject=claim.subject,
                                     denominator=claim.denominator, totals=totals)
            if not bound or not share_direction_supported(bound, claim.text, qualifications):
                unsupported = True
                break
            shares.extend(bound)
        ranked = []
        if ranking:
            claim_text = slide.title if _RANK.search(slide.title) else slide.message
            ranked = _reported_shares(displayed or selected, eligible, claim_text, ranking=True)
            unsupported = unsupported or not ranked
        if unsupported:
            _narrow(slide, replacements)
            notes.append(f"Slide {slide.id}: narrowed comparative wording without compatible reported shares")
            continue
        shares = list({item.id: item for item in shares}.values())
        added = shares
        if ranking:
            peers = _ranking_peers(ranked, eligible, text)
            if not peers:
                _narrow(slide, replacements)
                notes.append(f"Slide {slide.id}: narrowed ranking without a complete, consistent category comparison")
                continue
            if len(set(slide.observation_ids) | {item.id for item in peers}) > 40:
                _narrow(slide, replacements)
                notes.append(f"Slide {slide.id}: narrowed ranking whose complete evidence exceeds page capacity")
                continue
            added = list({item.id: item for item in [*shares, *peers]}.values())
            share_ids = {item.id for item in ranked}
            peer_ids = {item.id for item in peers}
            already_bound = next((cid for cid in slide.chart_ids if peer_ids <= set(charts[cid].observation_ids)), None)
            replaced = next((cid for cid in slide.chart_ids if set(charts[cid].observation_ids) <= share_ids), None)
            if replaced is None and already_bound is None:
                _narrow(slide, replacements)
                notes.append(f"Slide {slide.id}: narrowed ranking without space for its full comparison")
                continue
            chart_id = already_bound or stable_id("claim_comparison", *(item.id for item in peers))
            chart = ChartPlan(id=chart_id, title="Reported category shares", chart_type="bar",
                              available_chart_types=["bar", "line", "table"],
                              question="How do all reported category shares compare across these periods?",
                              observation_ids=[item.id for item in peers],
                              source_pages=sorted({e.page for item in peers for e in item.evidence}),
                              x_axis_title="Period", y_axis_title="Reported share (%)")
            if chart_id not in charts:
                result.charts.append(chart)
                charts[chart_id] = chart
            slide.chart_ids = [chart_id if cid == replaced else cid for cid in slide.chart_ids]
            for block in slide.visual_blocks:
                block.chart_ids = [chart_id if cid == replaced else cid for cid in block.chart_ids]
            notes.append(f"Slide {slide.id}: bound category ranking to all reconciled reported shares")
        visible = set(visible_observation_ids(slide, charts))
        missing = [item.id for item in shares if item.id not in visible]
        if missing:
            if (len(slide.visual_blocks) >= 4 or len(missing) > 12
                    or len(set(slide.observation_ids) | {item.id for item in shares}) > 40):
                _narrow(slide, replacements)
                notes.append(f"Slide {slide.id}: narrowed share wording without room for its evidence")
                continue
            slide.visual_blocks.insert(0, PresentationVisualBlock(role="table", observation_ids=missing))
            notes.append(f"Slide {slide.id}: added reported share values from the same source row")
        slide.observation_ids = list(dict.fromkeys([*slide.observation_ids, *(item.id for item in added)]))
        slide.source_pages = sorted(set(slide.source_pages) | {e.page for item in added for e in item.evidence})
        theme = themes.get(slide.theme_id)
        if theme:
            theme.observation_ids = list(dict.fromkeys([*theme.observation_ids, *(item.id for item in added)]))
            theme.chart_ids = list(dict.fromkeys([*theme.chart_ids, *slide.chart_ids]))
            theme.source_pages = sorted(set(theme.source_pages) | set(slide.source_pages))
        if restoring:
            slide.analytical_question = restoring.question
            slide.selection_reason = restoring.rationale
            restored_titles[narrowed_title].add(slide.title)
            notes.append(f"Slide {slide.id}: restored the selected takeaway after source-bound share validation")
    replacements.update({old: next(iter(titles)) for old, titles in restored_titles.items() if len(titles) == 1})
    for slide in plan.slides:
        slide.bullets = [replacements.get(text, text) for text in slide.bullets]
    from .presentation_summary_claims import prepare_summary_claims
    notes.extend(prepare_summary_claims(plan, eligible, by_id, charts, totals, definitions))
    plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *notes]))
    from .presentation_ratio_definitions import prepare_presentation_ratio_definitions
    from .presentation_period_scope import prepare_presentation_period_scope
    notes.extend(prepare_presentation_ratio_definitions(result, plan))
    prepare_presentation_period_scope(result, plan)
    if plan.planning_origin in {"topic_compilation", "topic_recovery"}:
        from adaptive_document_agent.agent.presentation_summary_selection import sync_selected_topic_summary_evidence
        sync_selected_topic_summary_evidence(result, plan)
    # Summary rebuilding can reintroduce duplicate references from another
    # source table after the earlier claim repair pass. Reconcile the final
    # visible references before export and on every repeated preparation.
    from adaptive_document_agent.validation.presentation_evidence_alignment import align_redundant_slide_evidence
    notes.extend(align_redundant_slide_evidence(plan, result.observations, result.charts))
    from adaptive_document_agent.agent.presentation_topic_scope_recovery import recover_cached_topic_claims
    notes.extend(recover_cached_topic_claims(plan, result))
    reconcile_composition_coverage(result, plan)
    plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *notes]))
    return notes
