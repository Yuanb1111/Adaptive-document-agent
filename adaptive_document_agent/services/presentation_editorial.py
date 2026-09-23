"""Observable presentation quality, separate from evidence and rendering safety.

These checks identify mechanical symptoms, not semantic truth. Only the model
may reorganise evidence or write a takeaway. Sparse documents are not required
to meet a chart count, slide count, or multi-chart quota.
"""

from collections import Counter
from dataclasses import dataclass
import re

from adaptive_document_agent.models import PipelineResult, PresentationPlan


@dataclass(frozen=True)
class EditorialFinding:
    code: str
    message: str
    slide_id: str | None = None


def _normal(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def distinct_findings(findings: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Remove exact repetition while preserving different claims and caveats."""
    # Keep signs, decimal points, units and all other punctuation in claims.
    # Token-only normalisation would incorrectly equate +5% with -5%.
    key_for = lambda text: " ".join(text.casefold().split())
    explained_labels = {key_for(label) for label, narrative in findings if label.strip() and narrative.strip()}
    output, seen = [], set()
    for label, narrative in findings:
        if not label.strip() and key_for(narrative) in explained_labels:
            continue
        key = (key_for(label), key_for(narrative))
        if key not in seen:
            seen.add(key)
            output.append((label, narrative))
    return output


def review_presentation(plan: PresentationPlan | None, result: PipelineResult) -> list[EditorialFinding]:
    """Read-only checks used in planning, QA and the download UI."""
    if plan is None:
        return [EditorialFinding("presentation_legacy", "Legacy evidence export: no analytical presentation plan is available.")]
    findings = []
    if plan.planning_origin == "topic_recovery":
        findings.append(EditorialFinding("presentation_degraded", "Question-first recovery: the model-selected analytical questions were retained, but the final slide wording needs editorial review."))
    elif plan.planning_origin == "fallback" or any(i.code == "presentation_plan_fallback" for i in result.validation_warnings):
        findings.append(EditorialFinding("presentation_degraded", "Evidence-only fallback: the analytical presentation plan could not be retained. Review the planning diagnostic before using this deck as a final report."))
    analysis = [s for s in plan.slides if s.slide_type == "analysis"]
    # This is a review request, not an instruction to merge incompatible bases
    # or force an industry checklist into the narrative.
    if analysis and not plan.coverage_notes:
        chart_map = {c.id: c for c in result.charts}
        selected = {oid for s in analysis for oid in s.observation_ids}
        selected.update(oid for s in analysis for b in s.visual_blocks for oid in b.observation_ids)
        selected.update(oid for s in analysis for cid in [*s.chart_ids, *(c for b in s.visual_blocks for c in b.chart_ids)]
                        if cid in chart_map for oid in chart_map[cid].observation_ids)
        from adaptive_document_agent.document_model import metric_key, period_sort_key
        def scope(o):
            dims = {**o.dimensions, **o.category_dimensions}
            return (metric_key(o), o.entity, o.unit, o.currency, o.ifrs_status,
                    tuple(sorted((k, str(v)) for k, v in dims.items()
                                 if k not in {"table_context", "section", "column_role", "period_basis"})))
        selected_scopes = {scope(o) for o in result.observations if o.id in selected}
        for key in sorted(selected_scopes, key=str):
            candidates = [o for o in result.observations if scope(o) == key and o.value is not None
                          and o.period and o.evidence and o.validation_status == "valid"]
            used = [o for o in candidates if o.id in selected]
            if used and candidates and max(period_sort_key(o.period) for o in candidates) > max(period_sort_key(o.period) for o in used):
                findings.append(EditorialFinding("presentation_recent_evidence_omitted",
                    f"More recent evidence exists for '{candidates[0].metric_original}'. Assess its comparable-period context separately; include it when material or explain exclusion in coverage_notes."))
    if analysis and not plan.themes:
        findings.append(EditorialFinding("presentation_missing_themes", "Analysis pages have no explicit theme plan. Organise the available evidence around distinct analytical questions."))
    topic_titles = set()
    for chart in result.charts:
        topic_titles.update({_normal(chart.title), _normal(chart.y_metric or "")})
    for obs in result.observations:
        topic_titles.update({_normal(obs.metric_original), _normal(obs.metric_canonical or "")})
    single_pages = []
    for slide in analysis:
        cids = set(slide.chart_ids) | {cid for b in slide.visual_blocks for cid in b.chart_ids}
        if len(cids) == 1:
            single_pages.append(slide)
        title = re.sub(r"\s+(trend|overview|analysis|trajectory)$", "", _normal(slide.title))
        if title in topic_titles or _normal(slide.title) in topic_titles:
            findings.append(EditorialFinding("presentation_topic_title", "The title only names the metric. State the supported finding or analytical question without adding unsupported numbers.", slide.id))
        if re.search(r"evidence.backed comparison|retained reported values|selected observations|supplied observations|paired observations exist|has observations for multiple periods", slide.message, re.I):
            findings.append(EditorialFinding("presentation_boilerplate", "Replace the generic subtitle with the actual scope, caveat or finding supported by this page.", slide.id))
        if re.match(r"(?i)^(?:ended\s+|(?:three|six|nine|twelve)\s+months?\s*$|as\s+(?:of|at)\s+)", slide.title.strip()):
            findings.append(EditorialFinding("presentation_header_fragment", "The title appears to be a source period-header fragment. Name the actual analytical subject shown in the selected evidence.", slide.id))
    # Detect an assembly-line symptom; request a semantic review, never merge
    # based on title tokens, chart count or shared source pages.
    if len(analysis) >= 4 and len(single_pages) / len(analysis) >= .75:
        findings.append(EditorialFinding("presentation_repetitive_composition", "Most analysis pages contain one chart. Review whether companion evidence answers the same question; retain standalone pages when justified and explain that choice in selection_reason."))
    for slide in plan.slides:
        if slide.slide_type not in {"executive_summary", "risks"}:
            continue
        repeated = [text for text, count in Counter(_normal(b) for b in slide.bullets if b.strip()).items() if count > 1]
        if repeated:
            findings.append(EditorialFinding("presentation_repeated_findings", "Repeated findings add no analytical information. Keep one supported explanation of each finding.", slide.id))
        if slide.slide_type == "risks" and slide.bullets and all(_normal(b) in topic_titles for b in slide.bullets):
            findings.append(EditorialFinding("presentation_empty_risk", "Risk bullets only name metrics. Explain the evidence-supported uncertainty or omit this optional page.", slide.id))
    return findings


def stamp_editorial_review(plan: PresentationPlan, result: PipelineResult, *, origin: str) -> PresentationPlan:
    """Server-owned status; never accept the model's self-assessment."""
    plan.planning_origin = origin
    findings = review_presentation(plan, result)
    plan.editorial_status = "degraded" if origin in {"fallback", "topic_recovery"} else "needs_review" if findings else "ready"
    plan.editorial_notes = [f"{f.slide_id + ': ' if f.slide_id else ''}{f.message}" for f in findings]
    return plan
