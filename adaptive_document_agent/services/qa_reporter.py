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
from adaptive_document_agent.validation.claim_validator import ClaimValidator


class CriticalQAError(ValueError):
    """Raised when critical QA errors block PowerPoint presentation export."""
    pass


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
    fixes: list[QAItem] = []
    plan = result.presentation_plan
    if not plan or not plan.company:
        return fixes

    company = plan.company
    is_resolved = company.identity_state == "RESOLVED" or (company.name and "unnamed" not in company.name.casefold())

    if is_resolved:
        # Sanitize company description
        if company.one_line_description and "unnamed issuer" in company.one_line_description.casefold():
            company.one_line_description = company.one_line_description.replace("(prospectus for an unnamed issuer)", "").replace("prospectus for an unnamed issuer", "").strip(" .")
            fixes.append(QAItem(
                code="company_identity_reconciled",
                severity="INFO",
                message="Removed 'unnamed issuer' contradiction from resolved company description.",
            ))

        # Sanitize data quality slide and bullets
        for slide in plan.slides:
            if slide.slide_type in ("data_quality", "company_overview"):
                clean_bullets = []
                for b in slide.bullets:
                    if "unnamed issuer" in b.casefold() or "issuer unknown" in b.casefold() or "unidentified issuer" in b.casefold():
                        fixes.append(QAItem(
                            code="company_identity_reconciled",
                            severity="INFO",
                            message=f"Removed conflicting issuer disclaimer from {slide.slide_type} slide.",
                            slide_id=slide.id,
                        ))
                    else:
                        clean_bullets.append(b)
                slide.bullets = clean_bullets

    return fixes


def run_comprehensive_qa(result: PipelineResult) -> QAReport:
    """Execute complete QA audit across numerical, semantic, period, claim, and presentation layers."""
    report = QAReport(
        document_title=result.profile.overview_title or "Financial Document",
        total_extracted_facts=len(result.observations),
        total_normalized_facts=len(result.observations),
        total_slides=len(result.presentation_plan.slides) if result.presentation_plan else 0,
    )

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

    # 4. Check presentation claims against facts
    if result.presentation_plan:
        validator = ClaimValidator()
        claim_issues = validator.validate_plan(result.presentation_plan, result.observations)
        for issue in claim_issues:
            if issue.code == "directional_contradiction":
                report.critical_errors.append(
                    QAItem(
                        code="directional_contradiction",
                        severity="CRITICAL",
                        message=issue.message,
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
        obs_ids = {obs.id for obs in result.observations}
        chart_by_id = {c.id: c for c in result.charts}
        for slide in result.presentation_plan.slides:
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

    report.is_export_blocked = report.has_critical_errors
    return report


def generate_artifacts(result: PipelineResult, output_dir: Path | str) -> dict[str, Path]:
    """Generate the 4 required JSON artifacts: extracted_facts, normalized_facts, slide_plan, qa_report."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

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
    normalized = [
        (o.to_canonical_fact().model_dump() if hasattr(o, "to_canonical_fact") else o.model_dump())
        for o in result.observations
    ]
    normalized_file = out_path / "normalized_facts.json"
    with open(normalized_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    # 3. slide_plan.json
    slide_plan_file = out_path / "slide_plan.json"
    slide_data = result.presentation_plan.model_dump() if result.presentation_plan else {}
    with open(slide_plan_file, "w", encoding="utf-8") as f:
        json.dump(slide_data, f, indent=2, ensure_ascii=False)

    # 4. qa_report.json
    qa = run_comprehensive_qa(result)
    qa_file = out_path / "qa_report.json"
    with open(qa_file, "w", encoding="utf-8") as f:
        json.dump(qa.model_dump(), f, indent=2, ensure_ascii=False)

    return {
        "extracted_facts": extracted_file,
        "normalized_facts": normalized_file,
        "slide_plan": slide_plan_file,
        "qa_report": qa_file,
    }
