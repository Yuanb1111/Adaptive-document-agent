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

_RANK = re.compile(r"\b(largest|smallest|highest|lowest)\b", re.I)
_SHARE = re.compile(r"\b(?:shares?|proportions?|percentage of (?:the )?total)\b", re.I)
_META = {"column_role", "table_context", "section", "period_basis"}


def _normalized(text):
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def _row(item):
    labels = {e.row_label.strip() for e in item.evidence if e.row_label and e.row_label.strip()}
    return next(iter(labels)) if len(labels) == 1 else ""


def _scope(item):
    return (item.effective_table_id, item.entity, item.period_basis, item.period_type,
            item.ifrs_status, tuple(sorted((k, v) for k, v in {**item.dimensions, **item.category_dimensions}.items()
                                          if k not in _META)))


def _share(item):
    if item.unit not in {"percent", "percentage", "%"}:
        return False
    labels = " ".join(e.column_label or "" for e in item.evidence)
    # ratio_share also covers expense/revenue and other unrelated denominators.
    # Even a coincidental sum of 100 cannot establish a common population.
    return bool(re.search(r"(?i)(?:%|percentage|share)\s*of\s*(?:the\s*)?total\b", labels))


def _position(item, text):
    label = re.sub(r"(?i)^subtotal\s+of\s+|\s+markets?$", "", _row(item))
    key = _normalized(label)
    return _normalized(text).find(key) if key else -1


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


def _reported_shares(selected, eligible, text, *, ranking=False):
    """Require the selected row, source table and periods, rather than label similarity."""
    subject = _claim_subject(selected, text, ranking=ranking)
    anchors = sorted((item for item in selected if item.effective_table_id and _row(item) == subject),
                     key=lambda item: (not _share(item), item.id)) if subject else []
    for anchor in anchors:
        periods = {item.period for item in selected if item.period and _scope(item) == _scope(anchor)
                   and _row(item) == _row(anchor)}
        if len(periods) < 2:
            continue
        matches = [item for item in eligible if _share(item) and _scope(item) == _scope(anchor)
                   and _row(item) == _row(anchor)]
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


def _share_motion(text):
    clauses = [part for part in re.split(r"[,;.]|\bwhile\b|\bwhereas\b", text, flags=re.I)
               if _SHARE.search(part)]
    up = any(re.search(r"(?i)\b(?:increas\w*|rais\w*|rose|rising|grew|growing|higher)\b", part) for part in clauses)
    down = any(re.search(r"(?i)\b(?:decreas\w*|declin\w*|fell|falling|lower|shr\w*)\b", part) for part in clauses)
    return up, down


def _share_direction_supported(shares, text):
    up, down = _share_motion(text)
    change = float(shares[-1].value) - float(shares[0].value)
    return not ((up and change <= 0) or (down and change >= 0))


def _narrow(slide, replacements):
    old = slide.title
    old_message = slide.message
    title = slide.section_title.strip()
    slide.title = title if title and not (_RANK.search(title) or _SHARE.search(title)) else "Reported measures"
    if _RANK.search(slide.message) or _SHARE.search(slide.message):
        # Keep independent qualifications even when the comparative sentence
        # has to go. Raw semantic decisions remain in presentation_topics.
        clauses = re.split(r"(?<=[.!?])\s+|;\s*", slide.message)
        retained = [part for part in clauses if not (_RANK.search(part) or _SHARE.search(part))]
        slide.message = " ".join(retained).strip() or "Reported values across the cited periods."
    slide.analytical_question = "How do the reported values vary across the cited periods?"
    slide.selection_reason = "The retained records support these reported values; the broader comparison was omitted."
    replacements[old] = slide.title
    if old_message and old_message != slide.message:
        replacements[old_message] = slide.message


def prepare_presentation_claims(result: PipelineResult, plan: PresentationPlan | None = None) -> list[str]:
    """Reconcile newly compiled or cached plans without additional model requests."""
    plan = plan or result.presentation_plan
    if plan is None:
        return []
    from adaptive_document_agent.agent.presentation_insight_recovery import recover_insight_narrative
    recover_insight_narrative(result, plan)
    reconcile_presentation_identity(plan, result)
    ambiguous = ambiguous_source_table_ids(result)
    eligible = [item for item in result.observations if item.value is not None and isfinite(item.value)
                and item.period and item.evidence and item.validation_status == "valid" and not item.anomaly_notes
                and not observation_uses_ambiguous_table(item, ambiguous)]
    by_id = {item.id: item for item in result.observations}
    charts = {chart.id: chart for chart in result.charts}
    themes = {theme.id: theme for theme in plan.themes}
    notes, replacements = [], {}
    for slide in plan.slides:
        if slide.slide_type != "analysis":
            continue
        text = slide.title + " " + slide.message
        if not (_RANK.search(text) or _SHARE.search(text)):
            continue
        ids = expanded_observation_ids(slide, charts)
        selected = [by_id[oid] for oid in ids if oid in by_id]
        ranking = bool(_RANK.search(text))
        pattern = _RANK if ranking else _SHARE
        claim_text = slide.title if pattern.search(slide.title) else slide.message
        shares = _reported_shares(selected, eligible, claim_text, ranking=ranking)
        share_text = slide.title if _SHARE.search(slide.title) else slide.message
        share_subject = _claim_subject(selected, share_text) if _SHARE.search(share_text) else ""
        if (not shares or not _share_direction_supported(shares, share_text)
                or (ranking and any(_share_motion(share_text)) and share_subject != _row(shares[0]))):
            _narrow(slide, replacements)
            notes.append(f"Slide {slide.id}: narrowed comparative wording without compatible reported shares")
            continue
        added = shares
        if _RANK.search(text):
            peers = _ranking_peers(shares, eligible, text)
            if not peers:
                _narrow(slide, replacements)
                notes.append(f"Slide {slide.id}: narrowed ranking without a complete, consistent category comparison")
                continue
            if len(set(slide.observation_ids) | {item.id for item in peers}) > 40:
                _narrow(slide, replacements)
                notes.append(f"Slide {slide.id}: narrowed ranking whose complete evidence exceeds page capacity")
                continue
            added = peers
            share_ids = {item.id for item in shares}
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
        else:
            visible = {oid for cid in slide.chart_ids for oid in charts[cid].observation_ids}
            visible.update(oid for block in slide.visual_blocks for oid in block.observation_ids)
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
    for slide in plan.slides:
        slide.bullets = [replacements.get(text, text) for text in slide.bullets]
    plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *notes]))
    return notes
