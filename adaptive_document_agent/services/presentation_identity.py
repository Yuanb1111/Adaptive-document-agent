"""Remove superseded identity limitations from presentation copy only."""

from __future__ import annotations

import re

from adaptive_document_agent.models import PipelineResult, PresentationPlan
from .company_extractor import is_company_identity_resolved


_MISSING_IDENTITY = re.compile(
    r"(?i)^(?:the\s+)?(?:company|issuer)(?:['’]s)?(?:\s+legal)?\s+(?:name|identity)\b"
    r"[^.;]{0,100}\b(?:not\s+(?:stated|provided|disclosed|known|identified|confirmed)"
    r"|cannot\s+be\s+(?:confirmed|identified)|unknown|unresolved|unavailable)\b"
    r"|^(?:(?:an?|the)\s+)?(?:unnamed|unidentified|unknown)\s+(?:issuer|company)\b"
    r"|^(?:the\s+)?(?:issuer|company)\s+(?:is\s+)?(?:unnamed|unidentified|unknown)\b"
)


def _resolved(plan: PresentationPlan | None, result: PipelineResult) -> bool:
    if not plan or not is_company_identity_resolved(plan.company):
        return False
    pages = set(plan.company.field_source_pages.get("name", []))
    retained_pages = {page.page_number for page in result.document.pages}
    return bool(pages and pages <= retained_pages)


def current_identity_copy(text: str, result: PipelineResult, plan: PresentationPlan | None = None) -> str:
    """Keep unrelated caveats, including neighboring sentences, unchanged.

    Original discovery notes remain on ``result.profile``. A resolved name
    without retained page citations cannot suppress an uncertainty warning.
    """
    if not _resolved(plan or result.presentation_plan, result):
        return text
    sentences = re.split(r"(?<=[.!?])\s+|;\s*|\s+but\s+|\s+however[,]?\s+|\n+", text, flags=re.I)
    retained = [part for part in sentences if not _MISSING_IDENTITY.search(part)
                or re.search(r"(?i)\b(?:conflict\w*|contradict\w*|ambiguous|multiple\s+names)\b", part)]
    return text if len(retained) == len(sentences) else " ".join(retained).strip()


def presentation_quality_notes(result: PipelineResult) -> list[str]:
    """Current audience/speaker notes; do not mutate the original JSON notes."""
    notes = [*result.profile.data_quality_notes,
             *(warning.message for warning in result.validation_warnings
               if warning.severity in {"error", "warning"})]
    return list(dict.fromkeys(copy for note in notes
                             if (copy := current_identity_copy(note, result))))


def reconcile_presentation_identity(plan: PresentationPlan, result: PipelineResult) -> None:
    """Clean already compiled introduction and caveat text after identity resolution."""
    if not _resolved(plan, result):
        return
    plan.company.one_line_description = current_identity_copy(plan.company.one_line_description, result, plan)
    for field in ("editorial_notes", "coverage_notes"):
        setattr(plan, field, [copy for note in getattr(plan, field)
                             if (copy := current_identity_copy(note, result, plan))])
    for theme in plan.themes:
        theme.caveats = [copy for note in theme.caveats
                        if (copy := current_identity_copy(note, result, plan))]
    for slide in plan.slides:
        if slide.slide_type == "data_quality":
            slide.message = current_identity_copy(slide.message, result, plan)
            paired = list(zip(slide.bullets, slide.bullet_observation_ids)) if slide.bullet_observation_ids else []
            if paired:
                pairs = [(copy, ids) for note, ids in paired
                         if (copy := current_identity_copy(note, result, plan))]
                slide.bullets = [copy for copy, _ in pairs]
                slide.bullet_observation_ids = [ids for _, ids in pairs]
            else:
                slide.bullets = [copy for note in slide.bullets
                                if (copy := current_identity_copy(note, result, plan))]
