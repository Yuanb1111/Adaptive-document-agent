"""Claim and directionality validator for presentation slides.

Validates that directional claims (increased, decreased, widened, narrowed)
and quantitative assertions in presentation slides match underlying facts.
"""

from __future__ import annotations

import re
from typing import Any

from adaptive_document_agent.document_model import period_sort_key
from adaptive_document_agent.models import Observation, PresentationPlan, PresentationSlide, ValidationIssue


_INCREASE_WORDS = ("increased", "grew", "growth", "rose", "expanded", "jumped", "up", "surged", "widened")
_DECREASE_WORDS = ("decreased", "declined", "contracted", "fell", "dropped", "down", "narrowed", "slumped")


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

            slide_text = " ".join([slide.title, slide.message, *slide.bullets])
            slide_issues = self.validate_slide_claims(slide.id, slide_text, slide_obs)
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
            key = (obs.metric_canonical or obs.metric_original).casefold()
            by_metric.setdefault(key, []).append(obs)

        for metric_name, obs_list in by_metric.items():
            if len(obs_list) < 2:
                continue
            # Sort by period
            sorted_obs = sorted(obs_list, key=lambda o: period_sort_key(o.period))
            first = sorted_obs[0]
            last = sorted_obs[-1]

            val_start = float(first.value)
            val_end = float(last.value)
            diff = val_end - val_start

            is_loss_metric = "loss" in metric_name or (val_start < 0 and val_end < 0)

            # Check if this metric is mentioned or relevant to the slide
            metric_tokens = [t for t in re.findall(r"[a-z]+", metric_name) if len(t) > 3]
            is_relevant = any(t in text_lower for t in metric_tokens) or len(by_metric) == 1

            if not is_relevant:
                continue

            # Directional verification
            claims_increase = any(w in text_lower for w in ("increased", "grew", "expanded", "rose", "growth"))
            claims_decrease = any(w in text_lower for w in ("decreased", "declined", "contracted", "fell", "dropped"))
            claims_narrowed = "narrowed" in text_lower
            claims_widened = "widened" in text_lower

            if is_loss_metric:
                # Loss metric: diff > 0 means loss became less negative (narrowed)
                # diff < 0 means loss became more negative (widened)
                if diff > 0 and claims_widened:
                    issues.append(
                        ValidationIssue(
                            code="directional_contradiction",
                            message=f"Slide {slide_id} claims loss 'widened' but underlying values narrowed from {val_start} to {val_end}.",
                            stage="presentation",
                            related_ids=[first.id, last.id],
                        )
                    )
                elif diff < 0 and claims_narrowed:
                    issues.append(
                        ValidationIssue(
                            code="directional_contradiction",
                            message=f"Slide {slide_id} claims loss 'narrowed' but underlying values widened from {val_start} to {val_end}.",
                            stage="presentation",
                            related_ids=[first.id, last.id],
                        )
                    )
            else:
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
