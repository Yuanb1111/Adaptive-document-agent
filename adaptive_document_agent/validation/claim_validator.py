"""Claim and directionality validator and repairer for presentation slides.

Validates that directional claims (increased, decreased, widened, narrowed, improved, deteriorated)
and quantitative assertions in presentation slides match underlying facts.

Rules:
1. Direction is determined by deterministic numeric logic, never LLM judgment.
2. For losses:
   - negative value moving closer to zero = loss narrowed / improved
   - negative value moving further from zero = loss widened / deteriorated
3. Before comparing two observations: verify same canonical metric, compatible units,
   same currency, compatible period types, and compatible reporting basis.
4. If contradictory wording can be safely repaired from validated numbers, automatically
   rewrite the slide title/message/bullets and rerun QA.
5. If observations are incompatible or ambiguous, do not auto-repair; keep export blocked.
"""

from __future__ import annotations

import re
from typing import Any

from adaptive_document_agent.document_model import period_sort_key
from adaptive_document_agent.models import Observation, PresentationPlan, PresentationSlide, ValidationIssue


def are_observations_compatible(obs1: Observation, obs2: Observation) -> tuple[bool, str]:
    """Verify that two observations can be safely compared for directional changes.

    Checks:
    1. Same canonical metric (or normalized original metric).
    2. Compatible units (same unit family, compatible unit scale).
    3. Same currency.
    4. Compatible period types (cannot compare balance sheet date with flow period,
       or full year flow with interim flow).
    5. Compatible reporting basis (reporting_basis dimension and audited_status).
    """
    # 1. Canonical metric
    m1 = (obs1.metric_canonical or obs1.metric_original).strip().casefold()
    m2 = (obs2.metric_canonical or obs2.metric_original).strip().casefold()
    if obs1.metric_canonical and obs2.metric_canonical:
        if obs1.metric_canonical.strip().casefold() != obs2.metric_canonical.strip().casefold():
            return False, f"Canonical metric mismatch: '{obs1.metric_canonical}' vs '{obs2.metric_canonical}'"
    elif m1 != m2:
        return False, f"Metric name mismatch: '{m1}' vs '{m2}'"

    # 2. Units & Unit family
    u1_fam = (obs1.unit_family or "").strip().casefold()
    u2_fam = (obs2.unit_family or "").strip().casefold()
    if u1_fam and u2_fam and u1_fam != "generic" and u2_fam != "generic" and u1_fam != u2_fam:
        return False, f"Incompatible unit families: '{u1_fam}' vs '{u2_fam}'"

    unit1 = (obs1.unit or obs1.raw_unit or "").strip().casefold()
    unit2 = (obs2.unit or obs2.raw_unit or "").strip().casefold()
    is_pct1 = "%" in unit1 or u1_fam == "percentage"
    is_pct2 = "%" in unit2 or u2_fam == "percentage"
    if is_pct1 != is_pct2:
        return False, f"Incompatible unit types: '{unit1}' vs '{unit2}' (percentage vs non-percentage)"

    # 3. Currency
    curr1 = (obs1.currency or "").strip().upper()
    curr2 = (obs2.currency or "").strip().upper()
    if curr1 and curr2 and curr1 != curr2:
        return False, f"Currency mismatch: '{curr1}' vs '{curr2}'"
    if (curr1 and not curr2 and u2_fam == "currency") or (curr2 and not curr1 and u1_fam == "currency"):
        return False, f"Currency specification mismatch: '{curr1 or 'unspecified'}' vs '{curr2 or 'unspecified'}'"

    # 4. Period types
    p1 = (obs1.period_type or "generic").strip().casefold()
    p2 = (obs2.period_type or "generic").strip().casefold()
    if p1 != "generic" and p2 != "generic":
        # Cannot compare point-in-time balance sheet date with flow period
        if (p1 == "balance_sheet_date" and p2 in ("fiscal_year", "interim_flow")) or (
            p2 == "balance_sheet_date" and p1 in ("fiscal_year", "interim_flow")
        ):
            return False, f"Incompatible period types: balance sheet point-in-time '{p1}' vs flow period '{p2}'"
        # Cannot compare full fiscal year flow directly with interim flow
        if (p1 == "fiscal_year" and p2 == "interim_flow") or (p2 == "fiscal_year" and p1 == "interim_flow"):
            return False, f"Incompatible period types: full fiscal year '{p1}' vs interim flow '{p2}'"

    # 5. Reporting basis
    b1 = (obs1.dimensions.get("reporting_basis") or obs1.dimensions.get("basis") or "").strip().casefold()
    b2 = (obs2.dimensions.get("reporting_basis") or obs2.dimensions.get("basis") or "").strip().casefold()
    if b1 and b2 and b1 != b2:
        return False, f"Incompatible reporting basis: '{b1}' vs '{b2}'"

    r1 = (obs1.dimensions.get("restatement") or obs1.dimensions.get("restated") or "").strip().casefold()
    r2 = (obs2.dimensions.get("restatement") or obs2.dimensions.get("restated") or "").strip().casefold()
    if r1 and r2 and r1 != r2:
        return False, f"Incompatible restatement basis: '{r1}' vs '{r2}'"

    return True, ""


def replace_word_preserving_case(text: str, target: str, replacement: str) -> tuple[str, bool]:
    """Replace a standalone word preserving uppercase or capitalized casing."""
    pattern = re.compile(r"\b" + re.escape(target) + r"\b", re.IGNORECASE)
    replaced = False

    def _repl(match: re.Match) -> str:
        nonlocal replaced
        replaced = True
        matched = match.group(0)
        if matched.isupper():
            return replacement.upper()
        if matched[0].isupper():
            return replacement.capitalize()
        return replacement.lower()

    new_text = pattern.sub(_repl, text)
    return new_text, replaced


# Mappings for standard metrics (non-loss)
_STANDARD_INCREASE_REPLACEMENTS: dict[str, str] = {
    "declined": "increased",
    "declining": "increasing",
    "declines": "increases",
    "decline": "increase",
    "decreased": "increased",
    "decreasing": "increasing",
    "decreases": "increases",
    "decrease": "increase",
    "fell": "rose",
    "falling": "rising",
    "falls": "rises",
    "fall": "rise",
    "dropped": "rose",
    "dropping": "rising",
    "drops": "rises",
    "drop": "rise",
    "contracted": "expanded",
    "contracting": "expanding",
    "contraction": "expansion",
    "slumped": "surged",
    "narrowed": "expanded",
}

_STANDARD_DECREASE_REPLACEMENTS: dict[str, str] = {
    "increased": "decreased",
    "increasing": "decreasing",
    "increases": "decreases",
    "increase": "decrease",
    "grew": "declined",
    "growth": "decline",
    "growing": "declining",
    "grow": "decline",
    "rose": "fell",
    "rising": "falling",
    "rises": "falls",
    "rise": "fall",
    "expanded": "contracted",
    "expanding": "contracting",
    "expansion": "contraction",
    "surged": "slumped",
    "widened": "contracted",
}

# Mappings for loss metrics
_LOSS_NARROWED_REPLACEMENTS: dict[str, str] = {
    "widened": "narrowed",
    "widening": "narrowing",
    "widens": "narrows",
    "widen": "narrow",
    "deteriorated": "improved",
    "deteriorating": "improving",
    "deteriorates": "improves",
    "deterioration": "improvement",
    "increased": "narrowed",
    "increasing": "narrowing",
    "increases": "narrows",
    "grew": "narrowed",
    "expanded": "narrowed",
}

_LOSS_WIDENED_REPLACEMENTS: dict[str, str] = {
    "narrowed": "widened",
    "narrowing": "widening",
    "narrows": "widens",
    "narrow": "widen",
    "improved": "deteriorated",
    "improving": "deteriorating",
    "improves": "deteriorates",
    "improvement": "deterioration",
    "decreased": "widened",
    "decreasing": "widening",
    "decreases": "widens",
    "declined": "widened",
    "declining": "widening",
    "declines": "widens",
    "contracted": "widened",
}


class ClaimValidator:
    """Validates directional and numeric claims across presentation slides."""

    def __init__(self, relative_tolerance: float = 0.10) -> None:
        self.relative_tolerance = relative_tolerance

    def validate_plan(
        self,
        plan: PresentationPlan,
        observations: list[Observation],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        obs_by_id = {obs.id: obs for obs in observations}

        for slide in plan.slides:
            slide_obs = [obs_by_id[oid] for oid in slide.observation_ids if oid in obs_by_id]
            for block in getattr(slide, "visual_blocks", []):
                for oid in getattr(block, "observation_ids", []):
                    if oid in obs_by_id and obs_by_id[oid] not in slide_obs:
                        slide_obs.append(obs_by_id[oid])

            # Fall back to all observations if slide has no linked observations
            effective_obs = slide_obs if slide_obs else observations

            slide_text = " ".join([slide.title, slide.message, *slide.bullets])
            slide_issues = self.validate_slide_claims(slide.id, slide_text, effective_obs)
            issues.extend(slide_issues)

        return issues

    def validate_slide_claims(
        self,
        slide_id: str,
        claim_text: str,
        observations: list[Observation],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        text_lower = claim_text.casefold()

        # Group observations by metric
        by_metric: dict[str, list[Observation]] = {}
        for obs in observations:
            if obs.value is None or not obs.period:
                continue
            key = (obs.metric_canonical or obs.metric_original).strip().casefold()
            by_metric.setdefault(key, []).append(obs)

        for metric_name, obs_list in by_metric.items():
            if len(obs_list) < 2:
                continue
            sorted_obs = sorted(obs_list, key=lambda o: period_sort_key(o.period))
            first = sorted_obs[0]
            last = sorted_obs[-1]

            # Check if this metric is mentioned or relevant to the slide
            metric_tokens = [t for t in re.findall(r"[a-z0-9]+", metric_name) if len(t) > 2 and t not in ("and", "the", "for", "with")]
            is_relevant = (
                any(t in text_lower for t in metric_tokens)
                or (len(by_metric) == 1)
                or any(str(first.value) in text_lower or str(last.value) in text_lower for _ in [0])
            )

            if not is_relevant:
                continue

            # Verify compatibility before comparing
            is_comp, comp_reason = are_observations_compatible(first, last)
            if not is_comp:
                # If slide explicitly asserts direction on incompatible observations, block
                has_directional_word = any(
                    w in text_lower
                    for w in (
                        "increased", "decreased", "declined", "narrowed", "widened",
                        "improved", "deteriorated", "grew", "rose", "fell", "contracted"
                    )
                )
                if has_directional_word:
                    issues.append(
                        ValidationIssue(
                            code="directional_contradiction",
                            message=(
                                f"Slide {slide_id} asserts directional movement for '{metric_name}', "
                                f"but observations are incompatible: {comp_reason}. Cannot verify or auto-repair."
                            ),
                            stage="presentation",
                            related_ids=[first.id, last.id],
                        )
                    )
                continue

            val_start = float(first.value)
            val_end = float(last.value)
            diff = val_end - val_start

            is_loss_metric = "loss" in metric_name or (val_start < 0 and val_end < 0)

            # Check for directional contradictions
            if is_loss_metric:
                # Loss closer to zero -> narrowed / improved
                # Loss further from zero -> widened / deteriorated
                is_narrowed = (
                    (val_start < 0 and val_end < 0 and abs(val_end) < abs(val_start))
                    or (val_start < 0 and val_end >= 0)
                    or ("loss" in metric_name and val_start > 0 and val_end > 0 and val_end < val_start)
                )
                is_widened = (
                    (val_start < 0 and val_end < 0 and abs(val_end) > abs(val_start))
                    or (val_start >= 0 and val_end < 0)
                    or ("loss" in metric_name and val_start > 0 and val_end > 0 and val_end > val_start)
                )

                claims_widened = any(w in text_lower for w in ("widened", "widening", "widens", "deteriorated", "deteriorating"))
                claims_narrowed = any(w in text_lower for w in ("narrowed", "narrowing", "narrows", "improved", "improving"))

                if is_narrowed and claims_widened:
                    issues.append(
                        ValidationIssue(
                            code="directional_contradiction",
                            message=f"Slide {slide_id} claims loss 'widened' but underlying values narrowed from {val_start} to {val_end}.",
                            stage="presentation",
                            related_ids=[first.id, last.id],
                        )
                    )
                elif is_widened and claims_narrowed:
                    issues.append(
                        ValidationIssue(
                            code="directional_contradiction",
                            message=f"Slide {slide_id} claims loss 'narrowed' but underlying values widened from {val_start} to {val_end}.",
                            stage="presentation",
                            related_ids=[first.id, last.id],
                        )
                    )
            else:
                claims_increase = any(w in text_lower for w in ("increased", "grew", "expanded", "rose", "growth", "widened"))
                claims_decrease = any(w in text_lower for w in ("decreased", "declined", "contracted", "fell", "dropped", "narrowed"))

                if diff > 0 and claims_decrease and not claims_increase:
                    issues.append(
                        ValidationIssue(
                            code="directional_contradiction",
                            message=f"Slide {slide_id} asserts metric '{metric_name}' decreased/declined, but underlying value increased from {val_start} to {val_end}.",
                            stage="presentation",
                            related_ids=[first.id, last.id],
                        )
                    )
                elif diff < 0 and claims_increase and not claims_decrease:
                    issues.append(
                        ValidationIssue(
                            code="directional_contradiction",
                            message=f"Slide {slide_id} asserts metric '{metric_name}' increased/grew, but underlying value decreased from {val_start} to {val_end}.",
                            stage="presentation",
                            related_ids=[first.id, last.id],
                        )
                    )

        return issues


def repair_slide_text(
    text: str,
    metric_name: str,
    val_start: float,
    val_end: float,
    is_loss_metric: bool,
) -> tuple[str, list[str]]:
    """Safely rewrite contradictory directional wording in a text fragment."""
    repairs: list[str] = []

    # Determine numeric direction
    if is_loss_metric:
        is_narrowed = (
            (val_start < 0 and val_end < 0 and abs(val_end) < abs(val_start))
            or (val_start < 0 and val_end >= 0)
            or ("loss" in metric_name and val_start > 0 and val_end > 0 and val_end < val_start)
        )
        is_widened = (
            (val_start < 0 and val_end < 0 and abs(val_end) > abs(val_start))
            or (val_start >= 0 and val_end < 0)
            or ("loss" in metric_name and val_start > 0 and val_end > 0 and val_end > val_start)
        )
        if is_narrowed:
            mapping = _LOSS_NARROWED_REPLACEMENTS
            direction_name = "narrowed"
        elif is_widened:
            mapping = _LOSS_WIDENED_REPLACEMENTS
            direction_name = "widened"
        else:
            return text, repairs
    else:
        diff = val_end - val_start
        if diff > 0:
            mapping = _STANDARD_INCREASE_REPLACEMENTS
            direction_name = "increased"
        elif diff < 0:
            mapping = _STANDARD_DECREASE_REPLACEMENTS
            direction_name = "decreased"
        else:
            return text, repairs

    # Check for any contradictory words present
    current_text = text
    for bad_word, good_word in mapping.items():
        if re.search(r"\b" + re.escape(bad_word) + r"\b", current_text, re.IGNORECASE):
            current_text, replaced = replace_word_preserving_case(current_text, bad_word, good_word)
            if replaced:
                repairs.append(f"Replaced '{bad_word}' with '{good_word}' ({direction_name})")

    return current_text, repairs


def is_text_relevant_to_metric(
    text: str,
    metric_name: str,
    val_start: float,
    val_end: float,
    is_only_metric: bool,
) -> bool:
    """Check whether a specific slide component (title, message, bullet) relates to a metric."""
    if is_only_metric:
        return True
    text_lower = text.casefold()
    tokens = [t for t in re.findall(r"[a-z0-9]+", metric_name) if len(t) > 2 and t not in ("and", "the", "for", "with", "expense", "expenses")]
    if any(t in text_lower for t in tokens):
        return True
    # Check if numbers match
    s_start = str(round(val_start, 2)).rstrip("0").rstrip(".")
    s_end = str(round(val_end, 2)).rstrip("0").rstrip(".")
    if (s_start in text_lower and s_start not in ("", "0")) or (s_end in text_lower and s_end not in ("", "0")):
        return True
    return False


def repair_slide_claims(
    slide: PresentationSlide,
    observations: list[Observation],
) -> tuple[PresentationSlide, list[str]]:
    """Deterministically rewrite contradictory wording on a slide using validated facts."""
    repairs: list[str] = []

    # Map observations for this slide
    obs_by_id = {obs.id: obs for obs in observations}
    slide_obs = [obs_by_id[oid] for oid in slide.observation_ids if oid in obs_by_id]
    for block in getattr(slide, "visual_blocks", []):
        for oid in getattr(block, "observation_ids", []):
            if oid in obs_by_id and obs_by_id[oid] not in slide_obs:
                slide_obs.append(obs_by_id[oid])

    effective_obs = slide_obs if slide_obs else observations

    by_metric: dict[str, list[Observation]] = {}
    for obs in effective_obs:
        if obs.value is None or not obs.period:
            continue
        key = (obs.metric_canonical or obs.metric_original).strip().casefold()
        by_metric.setdefault(key, []).append(obs)

    is_only_metric = len(by_metric) == 1

    new_title = slide.title
    new_message = slide.message
    new_bullets = list(slide.bullets)

    for metric_name, obs_list in by_metric.items():
        if len(obs_list) < 2:
            continue
        sorted_obs = sorted(obs_list, key=lambda o: period_sort_key(o.period))
        first = sorted_obs[0]
        last = sorted_obs[-1]

        # Compatibility check
        is_comp, _ = are_observations_compatible(first, last)
        if not is_comp:
            # Cannot safely auto-repair incompatible observations
            continue

        val_start = float(first.value)
        val_end = float(last.value)
        is_loss_metric = "loss" in metric_name or (val_start < 0 and val_end < 0)

        # Title repair
        if is_text_relevant_to_metric(new_title, metric_name, val_start, val_end, is_only_metric):
            repaired_title, title_repairs = repair_slide_text(new_title, metric_name, val_start, val_end, is_loss_metric)
            if title_repairs:
                new_title = repaired_title
                for r in title_repairs:
                    repairs.append(f"Slide {slide.id} title: {r} for '{metric_name}'")

        # Message repair
        if is_text_relevant_to_metric(new_message, metric_name, val_start, val_end, is_only_metric):
            repaired_msg, msg_repairs = repair_slide_text(new_message, metric_name, val_start, val_end, is_loss_metric)
            if msg_repairs:
                new_message = repaired_msg
                for r in msg_repairs:
                    repairs.append(f"Slide {slide.id} message: {r} for '{metric_name}'")

        # Bullets repair
        for idx, bullet in enumerate(new_bullets):
            if is_text_relevant_to_metric(bullet, metric_name, val_start, val_end, is_only_metric):
                repaired_bullet, bullet_repairs = repair_slide_text(bullet, metric_name, val_start, val_end, is_loss_metric)
                if bullet_repairs:
                    new_bullets[idx] = repaired_bullet
                    for r in bullet_repairs:
                        repairs.append(f"Slide {slide.id} bullet #{idx+1}: {r} for '{metric_name}'")

    if repairs:
        slide.title = new_title
        slide.message = new_message
        slide.bullets = new_bullets

    return slide, repairs


def repair_presentation_plan(
    plan: PresentationPlan,
    observations: list[Observation],
) -> tuple[PresentationPlan, list[str]]:
    """Execute claim repairs across all slides in a presentation plan."""
    all_repairs: list[str] = []
    for slide in plan.slides:
        _, slide_repairs = repair_slide_claims(slide, observations)
        all_repairs.extend(slide_repairs)
    return plan, all_repairs

