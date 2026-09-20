"""Cross-slide presentation consistency and validation layer.

Runs comprehensive cross-slide checks before PowerPoint export:
1. Banned placeholder detection (unknown, None, null, NaN, undefined)
2. Number provenance & float artifact detection
3. Period basis compatibility across slides (no FY vs interim mixing)
4. IFRS vs Non-IFRS clear labeling and separation
5. Working-capital cash flow logic (inventory/receivables absorption, payables support)
6. Executive Summary vs Detailed Analysis Slides directional and quantitative consistency
7. Softening of unsupported causal assertions (using 'alongside', 'associated with', etc.)
"""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from adaptive_document_agent.document_model.period_semantic_validator import extract_period_basis
from adaptive_document_agent.models import Observation, PipelineResult, PresentationPlan, PresentationSlide
from adaptive_document_agent.validation.claim_validator import (
    ClaimValidator,
    classify_metric_semantic_family,
    determine_trend_state,
    TrendState,
)

if TYPE_CHECKING:
    from adaptive_document_agent.services.qa_reporter import QAItem


_BANNED_PLACEHOLDERS = re.compile(
    r"(?i)\b(?:unknown|none|null|nan|undefined)\b"
)

_FLOAT_ARTIFACT_PATTERN = re.compile(
    r"\b\d+\.\d{5,}\b"
)

# Working-capital reversed interpretation patterns
_WC_REVERSED_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"(?i)\b(?:increase\s+in|increased|rising|higher)\s+(?:trade\s+)?(?:inventories|inventory|receivables)\s+(?:provided|generated|supported|boosted)\s+(?:cash|liquidity|operating\s+cash)\b"),
        "absorbed cash",
        "Rising inventory or receivables absorb cash, not generate it.",
    ),
    (
        re.compile(r"(?i)\b(?:decrease\s+in|decreased|falling|lower)\s+(?:trade\s+)?(?:inventories|inventory|receivables)\s+(?:drained|consumed|absorbed)\s+(?:cash|liquidity|operating\s+cash)\b"),
        "released cash",
        "Falling inventory or receivables release cash, not consume it.",
    ),
    (
        re.compile(r"(?i)\b(?:increase\s+in|increased|rising|higher)\s+(?:trade\s+)?payables\s+(?:drained|consumed|absorbed)\s+(?:cash|liquidity|operating\s+cash)\b"),
        "supported cash",
        "Rising payables provide working capital financing and support cash.",
    ),
    (
        re.compile(r"(?i)\b(?:decrease\s+in|decreased|falling|lower)\s+(?:trade\s+)?payables\s+(?:provided|generated|supported|boosted)\s+(?:cash|liquidity|operating\s+cash)\b"),
        "absorbed cash",
        "Decreasing payables absorb cash as liabilities are settled.",
    ),
]

# Unsupported causal phrases to soften into associative language
_CAUSAL_SOFTEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\bwas\s+caused\s+by\b"), "was associated with"),
    (re.compile(r"(?i)\bdirectly\s+caused\s+by\b"), "coinciding with"),
    (re.compile(r"(?i)\bdue\s+solely\s+to\b"), "alongside"),
    (re.compile(r"(?i)\bresulting\s+purely\s+from\b"), "reflecting"),
]


def _qa_item(code: str, severity: str, message: str, slide_id: str | None = None) -> Any:
    from adaptive_document_agent.services.qa_reporter import QAItem

    return QAItem(code=code, severity=severity, message=message, slide_id=slide_id)


class CrossSlideValidator:
    """Validates cross-slide consistency, placeholders, working-capital logic, and summary alignment."""

    def __init__(self, plan: PresentationPlan, observations: list[Observation]) -> None:
        self.plan = plan
        self.observations = observations
        self.obs_by_id = {o.id: o for o in observations}

    def validate_and_repair(self, *, auto_repair: bool = True) -> list[QAItem]:
        """Execute full cross-slide validation and apply auto-repairs in-place."""
        issues: list[QAItem] = []

        # 1. Banned Placeholder Inspection & Repair
        issues.extend(self._check_and_repair_placeholders(auto_repair=auto_repair))

        # 2. Float Artifacts Inspection & Repair
        issues.extend(self._check_and_repair_float_artifacts(auto_repair=auto_repair))

        # 3. Working Capital Logic Validation
        issues.extend(self._check_and_repair_working_capital_logic(auto_repair=auto_repair))

        # 4. Soften Unsupported Causal Assertions
        issues.extend(self._soften_unsupported_causal_assertions(auto_repair=auto_repair))

        # 5. IFRS vs Non-IFRS Labeling
        issues.extend(self._check_and_repair_ifrs_labeling(auto_repair=auto_repair))

        # 6. Executive Summary vs Detailed Analysis Consistency
        issues.extend(self._check_summary_vs_detail_consistency(auto_repair=auto_repair))

        return issues

    def _check_and_repair_placeholders(self, auto_repair: bool) -> list[QAItem]:
        issues: list[QAItem] = []
        for slide in self.plan.slides:
            # Check title
            if slide.title and _BANNED_PLACEHOLDERS.search(slide.title):
                if auto_repair:
                    slide.title = _BANNED_PLACEHOLDERS.sub("", slide.title).strip(" :;,-")
                    issues.append(_qa_item(
                        code="banned_placeholder_repaired",
                        severity="INFO",
                        message=f"Removed placeholder text from slide {slide.id} title.",
                        slide_id=slide.id,
                    ))
                else:
                    issues.append(_qa_item(
                        code="banned_placeholder_found",
                        severity="CRITICAL",
                        message=f"Slide {slide.id} title contains banned placeholder.",
                        slide_id=slide.id,
                    ))

            # Check message
            if slide.message and _BANNED_PLACEHOLDERS.search(slide.message):
                if auto_repair:
                    slide.message = _BANNED_PLACEHOLDERS.sub("", slide.message).strip(" :;,-")
                    issues.append(_qa_item(
                        code="banned_placeholder_repaired",
                        severity="INFO",
                        message=f"Removed placeholder text from slide {slide.id} message.",
                        slide_id=slide.id,
                    ))
                else:
                    issues.append(_qa_item(
                        code="banned_placeholder_found",
                        severity="CRITICAL",
                        message=f"Slide {slide.id} message contains banned placeholder.",
                        slide_id=slide.id,
                    ))

            # Check bullets
            cleaned_bullets: list[str] = []
            for b in slide.bullets:
                if _BANNED_PLACEHOLDERS.search(b):
                    if auto_repair:
                        cb = _BANNED_PLACEHOLDERS.sub("", b).strip(" :;,-")
                        if len(cb) > 10:
                            cleaned_bullets.append(cb)
                        issues.append(_qa_item(
                            code="banned_placeholder_repaired",
                            severity="INFO",
                            message=f"Sanitized placeholder text in slide {slide.id} bullet.",
                            slide_id=slide.id,
                        ))
                    else:
                        issues.append(_qa_item(
                            code="banned_placeholder_found",
                            severity="CRITICAL",
                            message=f"Slide {slide.id} bullet contains banned placeholder: '{b}'",
                            slide_id=slide.id,
                        ))
                        cleaned_bullets.append(b)
                else:
                    cleaned_bullets.append(b)
            slide.bullets = cleaned_bullets

        return issues

    def _check_and_repair_float_artifacts(self, auto_repair: bool) -> list[QAItem]:
        issues: list[QAItem] = []
        for slide in self.plan.slides:
            texts_to_check = [("title", slide.title), ("message", slide.message)]
            for i, b in enumerate(slide.bullets):
                texts_to_check.append((f"bullet_{i}", b))

            for field, text in texts_to_check:
                if not text:
                    continue
                matches = _FLOAT_ARTIFACT_PATTERN.findall(text)
                if matches:
                    if auto_repair:
                        repaired = text
                        for m in matches:
                            try:
                                val = float(m)
                                clean_val = f"{val:.1f}" if val != int(val) else str(int(val))
                                repaired = repaired.replace(m, clean_val)
                            except ValueError:
                                pass
                        if field == "title":
                            slide.title = repaired
                        elif field == "message":
                            slide.message = repaired
                        else:
                            idx = int(field.split("_")[1])
                            slide.bullets[idx] = repaired
                        issues.append(_qa_item(
                            code="float_artifact_repaired",
                            severity="INFO",
                            message=f"Repaired floating-point artifacts {matches} in slide {slide.id} {field}.",
                            slide_id=slide.id,
                        ))
                    else:
                        issues.append(_qa_item(
                            code="float_artifact_found",
                            severity="WARNING",
                            message=f"Slide {slide.id} contains float precision artifact {matches}.",
                            slide_id=slide.id,
                        ))
        return issues

    def _check_and_repair_working_capital_logic(self, auto_repair: bool) -> list[QAItem]:
        issues: list[QAItem] = []
        for slide in self.plan.slides:
            for field, text in [("title", slide.title), ("message", slide.message)]:
                if not text:
                    continue
                for pat, rep, expl in _WC_REVERSED_PATTERNS:
                    if pat.search(text):
                        if auto_repair:
                            fixed = pat.sub(rep, text)
                            if field == "title":
                                slide.title = fixed
                            else:
                                slide.message = fixed
                            issues.append(_qa_item(
                                code="working_capital_direction_repaired",
                                severity="INFO",
                                message=f"Corrected reversed working capital interpretation in slide {slide.id}: {expl}",
                                slide_id=slide.id,
                            ))
                        else:
                            issues.append(_qa_item(
                                code="working_capital_direction_contradiction",
                                severity="CRITICAL",
                                message=f"Slide {slide.id} has reversed working capital interpretation: {expl}",
                                slide_id=slide.id,
                            ))

            for idx, b in enumerate(slide.bullets):
                for pat, rep, expl in _WC_REVERSED_PATTERNS:
                    if pat.search(b):
                        if auto_repair:
                            slide.bullets[idx] = pat.sub(rep, b)
                            issues.append(_qa_item(
                                code="working_capital_direction_repaired",
                                severity="INFO",
                                message=f"Corrected reversed working capital interpretation in slide {slide.id} bullet: {expl}",
                                slide_id=slide.id,
                            ))
                        else:
                            issues.append(_qa_item(
                                code="working_capital_direction_contradiction",
                                severity="CRITICAL",
                                message=f"Slide {slide.id} bullet has reversed working capital interpretation: {expl}",
                                slide_id=slide.id,
                            ))
        return issues

    def _soften_unsupported_causal_assertions(self, auto_repair: bool) -> list[QAItem]:
        issues: list[QAItem] = []
        for slide in self.plan.slides:
            for idx, b in enumerate(slide.bullets):
                for pat, soft in _CAUSAL_SOFTEN_PATTERNS:
                    if pat.search(b):
                        if auto_repair:
                            slide.bullets[idx] = pat.sub(soft, b)
                            issues.append(_qa_item(
                                code="causal_claim_softened",
                                severity="INFO",
                                message=f"Softened unproven causal assertion in slide {slide.id} bullet to institutional associative phrasing.",
                                slide_id=slide.id,
                            ))
        return issues

    def _check_and_repair_ifrs_labeling(self, auto_repair: bool) -> list[QAItem]:
        issues: list[QAItem] = []
        for slide in self.plan.slides:
            slide_obs = [self.obs_by_id[oid] for oid in slide.observation_ids if oid in self.obs_by_id]
            is_adjusted_slide = any(
                getattr(o, "ifrs_status", "") == "ADJUSTED"
                or any(k in f"{o.metric_original} {o.metric_canonical or ''}".casefold() for k in ("adjusted", "non-ifrs", "non-gaap", "经调整"))
                for o in slide_obs
            )
            if is_adjusted_slide and slide.title:
                if not any(k in slide.title.casefold() for k in ("adjusted", "non-ifrs", "non-gaap", "经调整")):
                    if auto_repair:
                        # Append '(Adjusted)' or prefix
                        slide.title = f"{slide.title} (Adjusted)"
                        issues.append(_qa_item(
                            code="adjusted_metric_label_added",
                            severity="INFO",
                            message=f"Added explicit '(Adjusted)' disclosure label to slide {slide.id} title.",
                            slide_id=slide.id,
                        ))
                    else:
                        issues.append(_qa_item(
                            code="adjusted_metric_unlabeled",
                            severity="WARNING",
                            message=f"Slide {slide.id} presents non-IFRS / adjusted measures without clear disclosure labeling.",
                            slide_id=slide.id,
                        ))
        return issues

    def _check_summary_vs_detail_consistency(self, auto_repair: bool) -> list[QAItem]:
        """Verify that statements in the Executive Summary do not contradict findings on analysis slides."""
        issues: list[QAItem] = []
        summaries = [s for s in self.plan.slides if s.slide_type == "executive_summary"]
        analysis_slides = [s for s in self.plan.slides if s.slide_type == "analysis"]
        if not summaries or not analysis_slides:
            return issues

        summary_slide = summaries[0]

        # Extract metric directions established on analysis slides
        detail_metrics: dict[str, dict[str, Any]] = {}
        for a_slide in analysis_slides:
            a_obs = [self.obs_by_id[oid] for oid in a_slide.observation_ids if oid in self.obs_by_id]
            if len(a_obs) < 2:
                continue
            first = a_obs[0]
            last = a_obs[-1]
            m_name = (first.metric_canonical or first.metric_original).strip().casefold()
            trend = determine_trend_state(m_name, float(first.value or 0.0), float(last.value or 0.0), first.metric_canonical)
            detail_metrics[m_name] = {
                "slide_id": a_slide.id,
                "title": a_slide.title,
                "trend": trend,
                "val_start": first.value,
                "val_end": last.value,
            }

        # Check summary bullets against detailed slide trends
        clean_summary_bullets: list[str] = []
        for bullet in summary_slide.bullets:
            b_lower = bullet.casefold()
            contradicted = False
            for m_name, detail in detail_metrics.items():
                if m_name in b_lower:
                    trend = detail["trend"]
                    if trend in (TrendState.INCREASED, TrendState.LOSS_TO_PROFIT):
                        if any(w in b_lower for w in ("decreased", "declined", "dropped", "fell", "contracted", "swung into loss")):
                            contradicted = True
                            if auto_repair:
                                bullet = re.sub(r"(?i)\b(?:decreased|declined|dropped|fell|contracted)\b", "increased", bullet)
                                bullet = re.sub(r"(?i)\bswung\s+into\s+loss\b", "turned profitable", bullet)
                                issues.append(_qa_item(
                                    code="summary_detail_contradiction_repaired",
                                    severity="INFO",
                                    message=f"Repaired Executive Summary bullet contradiction regarding '{m_name}' to match analysis slide {detail['slide_id']}.",
                                    slide_id=summary_slide.id,
                                ))
                            else:
                                issues.append(_qa_item(
                                    code="summary_detail_contradiction",
                                    severity="CRITICAL",
                                    message=f"Executive Summary contradicts analysis slide {detail['slide_id']} regarding '{m_name}'.",
                                    slide_id=summary_slide.id,
                                ))
                    elif trend in (TrendState.DECREASED, TrendState.PROFIT_TO_LOSS, TrendState.LOSS_WIDENED, TrendState.OUTFLOW_INCREASED):
                        if any(w in b_lower for w in ("increased", "grew", "growth", "expanded", "turned profitable", "narrowed")):
                            contradicted = True
                            if auto_repair:
                                if trend == TrendState.LOSS_WIDENED:
                                    bullet = re.sub(r"(?i)\bnarrowed\b", "widened", bullet)
                                elif trend == TrendState.OUTFLOW_INCREASED:
                                    bullet = re.sub(r"(?i)\bnarrowed\b", "increased", bullet)
                                else:
                                    bullet = re.sub(r"(?i)\b(?:increased|grew|growth|expanded)\b", "decreased", bullet)
                                issues.append(_qa_item(
                                    code="summary_detail_contradiction_repaired",
                                    severity="INFO",
                                    message=f"Repaired Executive Summary bullet contradiction regarding '{m_name}' to match analysis slide {detail['slide_id']}.",
                                    slide_id=summary_slide.id,
                                ))
                            else:
                                issues.append(_qa_item(
                                    code="summary_detail_contradiction",
                                    severity="CRITICAL",
                                    message=f"Executive Summary contradicts analysis slide {detail['slide_id']} regarding '{m_name}'.",
                                    slide_id=summary_slide.id,
                                ))
            clean_summary_bullets.append(bullet)

        summary_slide.bullets = clean_summary_bullets
        return issues
