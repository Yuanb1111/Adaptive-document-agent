"""Comprehensive QA reporting and presentation export blocker.

Generates the 4 required JSON artifacts:
- extracted_facts.json
- normalized_facts.json
- slide_plan.json
- qa_report.json

Enforces strict export blocker on CRITICAL financial errors:
- 1000x magnitude error / unit scale mismatch
- Wrong currency
- Wrong period classification (e.g. balance sheet point-in-time date as FY)
- Directional claim contradiction
- Chart mismatch
- Company identity contradiction
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

from adaptive_document_agent.models import (
    CanonicalFact,
    Observation,
    PipelineResult,
    SourceEvidence,
)
from adaptive_document_agent.validation.claim_validator import (
    ClaimValidator,
    repair_presentation_plan,
)


class CriticalQAError(ValueError):
    """Raised when critical QA errors block PowerPoint presentation export."""
    def __init__(self, message: str, *, financial_report=None):
        super().__init__(message)
        self.financial_report = financial_report


class QAItem(BaseModel):
    code: str
    severity: Literal["CRITICAL", "WARNING", "INFO"]
    message: str
    slide_id: str | None = None
    related_ids: list[str] = Field(default_factory=list)


class QAReport(BaseModel):
    document_title: str
    total_extracted_facts: int = 0
    total_normalized_facts: int = 0
    total_slides: int = 0
    critical_errors: list[QAItem] = Field(default_factory=list)
    warnings: list[QAItem] = Field(default_factory=list)
    info: list[QAItem] = Field(default_factory=list)
    is_export_blocked: bool = False

    @property
    def has_critical_errors(self) -> bool:
        return len(self.critical_errors) > 0


def sanitize_company_identity_contradictions(result: PipelineResult) -> list[QAItem]:
    """Resolve and eliminate contradictions between Company at a Glance and Data Quality notes."""
    import re as _re
    fixes: list[QAItem] = []
    plan = result.presentation_plan
    if not plan or not plan.company:
        return fixes

    from adaptive_document_agent.services.company_extractor import is_company_identity_resolved

    company = plan.company
    # Authoritative resolution test
    is_resolved = is_company_identity_resolved(company)
    company_name = company.name or ""

    _UNNAMED_ISSUER_PHRASES = [
        "unnamed issuer",
        "issuer unnamed",
        "issuer unknown",
        "unidentified issuer",
        "unnamed company",
        "company unnamed",
        "issuer is unnamed",
        "company is unnamed",
        "issuer not named",
        "company not named",
        "unnamed entity",
        "issuer name is not stated",
        "company name is not stated",
        "issuer/company name is not stated",
        "the issuer name is not stated",
    ]

    def _contains_unnamed(text: str) -> bool:
        t = text.casefold()
        return any(phrase in t for phrase in _UNNAMED_ISSUER_PHRASES) or bool(_re.search(r"\bunnamed\s+(?:[\w-]+\s+){0,3}(?:company|issuer)\b", t))

    def _clean_text(text: str) -> str:
        """Remove or replace unnamed-issuer disclaimers when company is resolved."""
        result_text = text
        result_text = _re.sub(r"(?i)\bunnamed\s+(?:[\w-]+\s+){0,3}(?:company|issuer)\b", company_name, result_text)
        result_text = _re.sub(r"(?i)\(?(?:prospectus|document)\s+for\s+an?\s+(?:unnamed\s+issuer|issuer\s+unnamed)\)?", f"(prospectus for {company_name})", result_text)
        result_text = _re.sub(r"(?i)\b(?:unnamed\s+issuer|issuer\s+unnamed)\b", company_name, result_text)
        result_text = _re.sub(r"(?i)\b(?:unnamed\s+company|company\s+unnamed)\b", company_name, result_text)
        result_text = _re.sub(r"(?i)\b(?:issuer|company)\s+(?:is\s+)?unnamed\b", company_name, result_text)
        result_text = _re.sub(r"(?i)\bissuer\s+unknown\b", company_name, result_text)
        result_text = _re.sub(r"(?i)\bunidentified\s+issuer\b", company_name, result_text)
        result_text = _re.sub(r"(?i)\b(?:the\s+)?(?:issuer|company)(?:/company)?\s+name\s+is\s+not\s+stated\.?\s*", "", result_text)
        result_text = _re.sub(r"(?i)\b(?:the\s+)?(?:issuer|company)\s+(?:is\s+)?not\s+named\.?\s*", "", result_text)
        result_text = _re.sub(r"[ \t]{2,}", " ", result_text).strip(" .")
        return result_text

    if is_resolved:
        name_pages = company.field_source_pages.get("name", []) if hasattr(company, "field_source_pages") and company.field_source_pages else company.source_pages
        analysis_ranges = getattr(result.profile, "analysis_page_ranges", []) if hasattr(result, "profile") and result.profile else []
        is_outside_range = False
        if analysis_ranges and name_pages:
            is_outside_range = all(
                not any(start <= p <= end for start, end in analysis_ranges)
                for p in name_pages
            )

        # Sanitize profile data_quality_notes
        if hasattr(result, "profile") and result.profile:
            cleaned_notes = []
            for note in result.profile.data_quality_notes:
                if _contains_unnamed(note):
                    if is_outside_range:
                        pages_str = ", ".join(f"p. {p}" for p in sorted(set(name_pages))[:3]) if name_pages else "introductory disclosures"
                        cleaned = f"Company identity ({company_name}) verified from {pages_str} outside the financial analysis range; core financial tables refer to the issuer as 'the Company' or 'the Group'."
                    else:
                        cleaned = _clean_text(note)
                    if cleaned and cleaned not in cleaned_notes:
                        cleaned_notes.append(cleaned)
                    fixes.append(QAItem(
                        code="company_identity_reconciled",
                        severity="INFO",
                        message="Reconciled company identity with profile data quality notes.",
                    ))
                else:
                    cleaned_notes.append(note)
            if is_outside_range and not any(company_name in n for n in cleaned_notes):
                pages_str = ", ".join(f"p. {p}" for p in sorted(set(name_pages))[:3]) if name_pages else "introductory disclosures"
                cleaned_notes.append(
                    f"Company identity ({company_name}) verified from {pages_str} outside the financial analysis range; core financial tables refer to the issuer as 'the Company' or 'the Group'."
                )
            result.profile.data_quality_notes = cleaned_notes

        # Sanitize validation_warnings
        if hasattr(result, "validation_warnings"):
            result.validation_warnings = [
                w for w in result.validation_warnings
                if not (hasattr(w, "message") and _contains_unnamed(w.message))
            ]

        # Sanitize company description
        if company.one_line_description and _contains_unnamed(company.one_line_description):
            cleaned = _clean_text(company.one_line_description)
            if cleaned != company.one_line_description:
                company.one_line_description = cleaned
                fixes.append(QAItem(
                    code="company_identity_reconciled",
                    severity="INFO",
                    message="Removed 'unnamed issuer' contradiction from resolved company description.",
                ))

        # Presentation and slide titles are part of the same identity surface.
        if plan.title and _contains_unnamed(plan.title):
            plan.title = _clean_text(plan.title)
            fixes.append(QAItem(
                code="company_identity_reconciled",
                severity="INFO",
                message="Removed issuer-name contradiction from presentation title.",
            ))

        # Sanitize all slides: bullets, message, subtitle
        for slide in plan.slides:
            if slide.title and _contains_unnamed(slide.title):
                slide.title = _clean_text(slide.title)
                fixes.append(QAItem(
                    code="company_identity_reconciled",
                    severity="INFO",
                    message=f"Removed issuer-name contradiction from {slide.slide_type} slide title.",
                    slide_id=slide.id,
                ))
            # Bullets: remove bullets that are unnamed-issuer disclaimers
            clean_bullets = []
            for b in slide.bullets:
                if _contains_unnamed(b):
                    fixes.append(QAItem(
                        code="company_identity_reconciled",
                        severity="INFO",
                        message=f"Removed conflicting issuer disclaimer from {slide.slide_type} slide.",
                        slide_id=slide.id,
                    ))
                else:
                    clean_bullets.append(b)
            slide.bullets = clean_bullets

            # Message: clean inline unnamed-issuer text
            if slide.message and _contains_unnamed(slide.message):
                slide.message = _clean_text(slide.message)
                fixes.append(QAItem(
                    code="company_identity_reconciled",
                    severity="INFO",
                    message=f"Removed issuer-name disclaimer from {slide.slide_type} slide message.",
                    slide_id=slide.id,
                ))

            # Subtitle: clean inline unnamed-issuer text
            if hasattr(slide, "subtitle") and slide.subtitle and _contains_unnamed(slide.subtitle):
                slide.subtitle = _clean_text(slide.subtitle)
                fixes.append(QAItem(
                    code="company_identity_reconciled",
                    severity="INFO",
                    message=f"Removed issuer-name disclaimer from {slide.slide_type} slide subtitle.",
                    slide_id=slide.id,
                ))
    else:
        if company.identity_state != "UNRESOLVED":
            company.identity_state = "UNRESOLVED"
            fixes.append(QAItem(
                code="company_identity_marked_unresolved",
                severity="INFO",
                message="Marked company identity state as UNRESOLVED due to unevidenced or generic company name.",
            ))
        for slide in plan.slides:
            if slide.slide_type == "company_overview" and slide.title.casefold() in {"company at a glance", "company overview"}:
                slide.title = "Document at a Glance"
                fixes.append(QAItem(
                    code="company_overview_title_aligned",
                    severity="INFO",
                    message="Updated company overview slide title to 'Document at a Glance' for unresolved issuer.",
                    slide_id=slide.id,
                ))
        # Ensure Data Quality reflects unresolved issuer if not already mentioned
        if hasattr(result, "profile") and result.profile:
            has_unnamed_note = any(_contains_unnamed(n) for n in result.profile.data_quality_notes)
            if not has_unnamed_note:
                result.profile.data_quality_notes.append("Issuer name is not stated in supplied source pages; document analysed as general corporate document.")

    return fixes


def repair_presentation_plan_claims(result: PipelineResult) -> list[str]:
    """Execute the automatic claim repair loop:
    Presentation Plan -> Claim Validation -> Repair contradictory wording -> Revalidate.
    """
    if not result.presentation_plan:
        return []
    plan, repairs = repair_presentation_plan(result.presentation_plan, result.observations)
    result.presentation_plan = plan
    return repairs


# Patterns in slide titles / messages that claim a multi-period trend
_MULTI_PERIOD_CLAIM_PATTERNS = [
    re.compile(r"(?i)\bacross\s+the\s+(?:track\s+record|review)\s+period\b"),
    re.compile(r"(?i)\bover\s+the\s+(?:track\s+record|review|reporting|full)\s+period\b"),
    re.compile(r"(?i)\bthroughout\s+the\s+(?:track\s+record|review|reporting)\s+period\b"),
    re.compile(r"(?i)\bover\s+(?:FY|the)\s*20\d{2}[-–]20\d{2}\b"),
    re.compile(r"(?i)\byear(?:-over-year|[- ]on[- ]year|ly\s+(?:growth|increase|decrease|decline|trend))\b"),
]


def check_evidence_completeness_for_title_claims(
    plan: PresentationPlan,
    observations: list[Observation],
) -> list[QAItem]:
    """Check that slides claiming multi-period trends have ≥2 distinct periods in evidence.

    If a slide title asserts a multi-period claim (e.g. 'across the Track Record Period')
    but has fewer than 2 distinct observation periods, repair the title by stripping the
    unsupported multi-period qualifier.
    """
    issues: list[QAItem] = []
    obs_by_id = {obs.id: obs for obs in observations}

    for slide in plan.slides:
        if slide.slide_type in ("cover", "contents", "appendix", "data_quality", "section_divider", "divider"):
            continue
        title = slide.title or ""
        if not any(p.search(title) for p in _MULTI_PERIOD_CLAIM_PATTERNS):
            continue

        # Count distinct periods among linked observations
        slide_obs = [obs_by_id[oid] for oid in slide.observation_ids if oid in obs_by_id]
        for block in getattr(slide, "visual_blocks", []):
            for oid in getattr(block, "observation_ids", []):
                if oid in obs_by_id and obs_by_id[oid] not in slide_obs:
                    slide_obs.append(obs_by_id[oid])

        distinct_periods: set[str] = {obs.period for obs in slide_obs if obs.period}
        if len(distinct_periods) < 2:
            # Repair: strip the unsupported multi-period qualifier from the title
            repaired_title = title
            for pat in _MULTI_PERIOD_CLAIM_PATTERNS:
                repaired_title = pat.sub("", repaired_title).strip(" .,;–-")
            if repaired_title and repaired_title != title:
                slide.title = repaired_title
                issues.append(QAItem(
                    code="evidence_incomplete_title_claim",
                    severity="WARNING",
                    message=(
                        f"Slide {slide.id} title claimed multi-period trend "
                        f"but has only {len(distinct_periods)} distinct period(s) in evidence. "
                        f"Title updated: '{title}' → '{repaired_title}'"
                    ),
                    slide_id=slide.id,
                ))
            else:
                issues.append(QAItem(
                    code="evidence_incomplete_title_claim",
                    severity="WARNING",
                    message=(
                        f"Slide {slide.id} title claimed multi-period trend "
                        f"but has only {len(distinct_periods)} distinct period(s) in evidence: '{title}'"
                    ),
                    slide_id=slide.id,
                ))

    return issues

def run_comprehensive_qa(result: PipelineResult, auto_repair: bool = True) -> QAReport:
    """Execute complete QA audit across numerical, semantic, period, claim, and presentation layers."""
    if auto_repair and result.presentation_plan and result.presentation_plan.company:
        from adaptive_document_agent.services.company_extractor import extract_structured_company_fields
        result.presentation_plan.company = extract_structured_company_fields(result.presentation_plan.company, result)

    report = QAReport(
        document_title=result.profile.overview_title or "Financial Document",
        total_extracted_facts=len(result.observations),
        total_normalized_facts=len(result.observations),
        total_slides=len(result.presentation_plan.slides) if result.presentation_plan else 0,
    )

    if auto_repair:
        from .single_metric_slides import enrich_single_metric_slides
        for slide_id in enrich_single_metric_slides(result):
            report.info.append(QAItem(code="single_metric_enriched", severity="INFO", slide_id=slide_id,
                message="Enriched comparable single-metric evidence with a hero chart and deterministic period statistics."))

    # 1. Resolve company identity contradictions
    identity_fixes = sanitize_company_identity_contradictions(result)
    report.info.extend(identity_fixes)

    # 2. Check 1000x magnitude and unit scale errors
    for obs in result.observations:
        if obs.value is not None and obs.unit_scale:
            # Check for double scaling trap: normalized_value vs raw_value
            # e.g., if raw is 92.2m (-92237) and value is -92.2bn (-92237000000)
            raw_str = str(obs.raw_value).replace(",", "")
            try:
                raw_num = float(raw_str)
                if abs(raw_num) > 0 and abs(obs.value) > 0:
                    ratio = abs(obs.value) / abs(raw_num)
                    expected_scale = obs.unit_scale
                    if expected_scale > 1.0 and abs(ratio - (expected_scale * 1000.0)) < 1.0:
                        report.critical_errors.append(
                            QAItem(
                                code="1000x_magnitude_error",
                                severity="CRITICAL",
                                message=f"Fact {obs.id} ({obs.metric_original}) suffered 1000x magnitude error: raw={raw_num}, value={obs.value}.",
                                related_ids=[obs.id],
                            )
                        )
            except ValueError:
                pass

    # 3. Check period classification errors
    for obs in result.observations:
        period = (obs.period or "").strip()
        # "30 Apr 2025" or "31 Dec 2024" should never be classified as FY
        if re.search(r"\b\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}\b", period):
            if obs.period_type == "fiscal_year":
                report.critical_errors.append(
                    QAItem(
                        code="wrong_period_classification",
                        severity="CRITICAL",
                        message=f"Point-in-time date '{period}' on fact {obs.id} was erroneously classified as fiscal_year.",
                        related_ids=[obs.id],
                    )
                )

    # 4. Check presentation claims against facts (with auto-repair loop)
    if result.presentation_plan:
        if auto_repair:
            repairs = repair_presentation_plan_claims(result)
            for r in repairs:
                report.info.append(
                    QAItem(
                        code="claim_contradiction_repaired",
                        severity="INFO",
                        message=r,
                    )
                )

            # 4b. Check evidence completeness for multi-period title claims
            evidence_issues = check_evidence_completeness_for_title_claims(
                result.presentation_plan, result.observations
            )
            for ei in evidence_issues:
                report.warnings.append(ei)

        # Revalidation pass
        validator = ClaimValidator()
        claim_issues = validator.validate_plan(result.presentation_plan, result.observations)
        reported_claim_transitions: set[tuple[str, str, str, str]] = set()
        for issue in claim_issues:
            if issue.code == "directional_contradiction":
                # A single underlying contradiction can appear in a slide title,
                # message, and bullets.  QA reports the root issue once per
                # slide, metric, and period transition while the structured
                # validator remains component-aware for automatic repairs.
                transition_key = (
                    str(getattr(issue, "slide_id", "")),
                    str(getattr(issue, "metric_name", "")).strip().casefold(),
                    str(getattr(issue, "start_period", "")),
                    str(getattr(issue, "end_period", "")),
                )
                if transition_key in reported_claim_transitions:
                    continue
                reported_claim_transitions.add(transition_key)
                report.critical_errors.append(
                    QAItem(
                        code="directional_contradiction",
                        severity="CRITICAL",
                        message=issue.message,
                        slide_id=getattr(issue, "slide_id", None) or None,
                        related_ids=issue.related_ids,
                    )
                )
            else:
                report.warnings.append(
                    QAItem(
                        code=issue.code,
                        severity="WARNING",
                        message=issue.message,
                        related_ids=issue.related_ids,
                    )
                )

    # 5. Check chart mismatches
    if result.presentation_plan:
        # Imported lazily to avoid making the QA model layer depend on PPTX at
        # module-import time.
        from adaptive_document_agent.document_model.topic_matcher import (
            extract_topic_tokens,
            get_slide_context,
            is_positive_topic_mismatch,
            metrics_match_topic,
        )

        obs_ids = {obs.id for obs in result.observations}
        obs_by_id = {obs.id: obs for obs in result.observations}
        chart_by_id = {c.id: c for c in result.charts}
        for slide in result.presentation_plan.slides:
            slide_ctx = get_slide_context(slide)

            # Validate directly linked table/KPI rows against a specific slide
            # topic using positive evidence of mismatch. Deduplicated by metric family.
            if slide.slide_type == "analysis":
                is_hybrid_kpi_slide = (
                    getattr(slide, "layout", None) in {"chart_plus_kpis", "table_plus_kpis", "chart_with_data"}
                    and bool(getattr(slide, "chart_ids", None))
                )
                mismatched_by_family: dict[str, list[Observation]] = {}
                for observation_id in slide.observation_ids:
                    observation = obs_by_id.get(observation_id)
                    if observation and is_positive_topic_mismatch(observation, slide, is_supporting_kpi=is_hybrid_kpi_slide):
                        family = (
                            getattr(observation, "metric_canonical", "")
                            or getattr(observation, "canonical_name", "")
                            or observation.metric_original
                        ).strip().casefold()
                        mismatched_by_family.setdefault(family, []).append(observation)

                for family, m_obs in mismatched_by_family.items():
                    first_obs = m_obs[0]
                    report.critical_errors.append(
                        QAItem(
                            code="slide_topic_mismatch",
                            severity="CRITICAL",
                            message=(
                                f"Slide {slide.id} topic '{slide.title}' is not aligned with linked "
                                f"metric '{first_obs.metric_original}'."
                            ),
                            slide_id=slide.id,
                            related_ids=[item.id for item in m_obs],
                        )
                    )

            for cid in getattr(slide, "chart_ids", []):
                if cid not in chart_by_id:
                    report.critical_errors.append(
                        QAItem(
                            code="chart_mismatch",
                            severity="CRITICAL",
                            message=f"Slide {slide.id} references missing chart {cid}.",
                            slide_id=slide.id,
                        )
                    )
                else:
                    chart = chart_by_id[cid]
                    missing_obs = set(chart.observation_ids) - obs_ids
                    if missing_obs:
                        report.critical_errors.append(
                            QAItem(
                                code="chart_observation_missing",
                                severity="CRITICAL",
                                message=f"Chart {cid} on slide {slide.id} references missing observations {sorted(missing_obs)}.",
                                slide_id=slide.id,
                            )
                        )
                    elif slide.slide_type == "analysis":
                        chart_observations = [obs_by_id[oid] for oid in chart.observation_ids if oid in obs_by_id]
                        chart_canon = (
                            chart_observations[0].metric_canonical
                            or chart_observations[0].metric_original
                        ).strip().casefold() if chart_observations else ""
                        
                        mismatched_by_family: dict[str, list[Observation]] = {}
                        for item in chart_observations:
                            if is_positive_topic_mismatch(item, slide):
                                family = (
                                    getattr(item, "metric_canonical", "")
                                    or getattr(item, "canonical_name", "")
                                    or item.metric_original
                                ).strip().casefold()
                                mismatched_by_family.setdefault(family, []).append(item)

                        for family, m_obs in mismatched_by_family.items():
                            report.critical_errors.append(
                                QAItem(
                                    code="chart_topic_mismatch",
                                    severity="CRITICAL",
                                    message=(
                                        f"Chart {cid} on slide {slide.id} contains metrics unrelated to "
                                        f"the slide topic '{slide.title}': "
                                        + ", ".join(dict.fromkeys(item.metric_original for item in m_obs))
                                    ),
                                    slide_id=slide.id,
                                    related_ids=[item.id for item in m_obs],
                                )
                            )

    # 6. PPT layout QA (scatter readability, cramped multi-chart splitting, long paragraph overflow)
    from .presentation_editorial import review_presentation
    for item in review_presentation(result.presentation_plan, result):
        report.warnings.append(QAItem(code=item.code, severity="WARNING", message=item.message, slide_id=item.slide_id))

    if result.presentation_plan:
        from adaptive_document_agent.validation.layout_qa import validate_presentation_layout

        layout_issues = validate_presentation_layout(result, auto_repair=auto_repair)
        for issue in layout_issues:
            if issue.severity == "CRITICAL":
                report.critical_errors.append(issue)
            elif issue.severity == "WARNING":
                report.warnings.append(issue)
            else:
                report.info.append(issue)

    # 7. Cross-slide validation (placeholders, float artifacts, working capital, summary vs detail consistency)
    if result.presentation_plan:
        from adaptive_document_agent.validation.cross_slide_validator import CrossSlideValidator

        cross_issues = CrossSlideValidator(result.presentation_plan, result.observations).validate_and_repair(auto_repair=auto_repair)
        for issue in cross_issues:
            if issue.severity == "CRITICAL":
                report.critical_errors.append(issue)
            elif issue.severity == "WARNING":
                report.warnings.append(issue)
            else:
                report.info.append(issue)

    from adaptive_document_agent.validation.presentation_data_qa import validate_presentation_data
    for issue in validate_presentation_data(result):
        if issue.severity == "CRITICAL":
            report.critical_errors.append(issue)
        else:
            report.warnings.append(issue)
    report.is_export_blocked = report.has_critical_errors
    return report


def generate_artifacts(result: PipelineResult, output_dir: Path | str) -> dict[str, Path]:
    """Generate the 4 required JSON artifacts: extracted_facts, normalized_facts, slide_plan, qa_report."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Run QA and claim repair loop before writing artifacts
    qa = run_comprehensive_qa(result, auto_repair=True)

    # 1. extracted_facts.json
    extracted = [
        {
            "id": o.id,
            "metric_original": o.metric_original,
            "raw_value": o.raw_value,
            "raw_unit": o.raw_unit,
            "period": o.period,
            "currency": o.currency,
            "evidence": [e.model_dump() for e in o.evidence],
            "confidence": o.confidence,
        }
        for o in result.observations
    ]
    extracted_file = out_path / "extracted_facts.json"
    with open(extracted_file, "w", encoding="utf-8") as f:
        json.dump(extracted, f, indent=2, ensure_ascii=False)

    # 2. normalized_facts.json
    from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer
    normalized = [
        fact.model_dump()
        for fact in FinancialNormalizer.to_canonical_facts(result.observations)
    ]
    normalized_file = out_path / "normalized_facts.json"
    with open(normalized_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    # 3. slide_plan.json (reflecting repaired plan)
    slide_plan_file = out_path / "slide_plan.json"
    slide_data = result.presentation_plan.model_dump() if result.presentation_plan else {}
    with open(slide_plan_file, "w", encoding="utf-8") as f:
        json.dump(slide_data, f, indent=2, ensure_ascii=False)

    # 4. qa_report.json
    qa_file = out_path / "qa_report.json"
    with open(qa_file, "w", encoding="utf-8") as f:
        json.dump(qa.model_dump(), f, indent=2, ensure_ascii=False)

    return {
        "extracted_facts": extracted_file,
        "normalized_facts": normalized_file,
        "slide_plan": slide_plan_file,
        "qa_report": qa_file,
    }
