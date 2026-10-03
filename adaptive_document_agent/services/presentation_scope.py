"""Audience-visible coverage boundaries, separate from the raw validation audit."""

import json
import re
from .presentation_brief import BriefItem
from .presentation_identity import current_identity_copy


def scope_items(result):
    plan = result.presentation_plan
    if plan is None:
        return []
    retained = {theme.id for theme in plan.themes}
    items, seen = [], set()

    def add(title, text, pages=()):
        text = current_identity_copy(text, result)
        if text and (title, text) not in seen:
            items.append(BriefItem(title, text, list(pages)))
            seen.add((title, text))

    for issue in result.validation_warnings:
        if issue.code == "presentation_topic_validation":
            try:
                draft = json.loads(issue.message)
                topic = draft["topic"]
            except (ValueError, KeyError, TypeError):
                continue
            if draft.get("phase") == "initial" and topic.get("id") not in retained:
                add("Not covered: " + topic.get("title", "Selected topic"),
                    "This selected topic could not be safely presented. " + str(draft.get("error", "Source validation failed.")))
    for note in plan.coverage_notes:
        if not _contradicted_by_retained_content(note, result):
            add("Coverage boundary", note)
    for theme in plan.themes:
        for caveat in theme.caveats:
            add(theme.title, caveat, theme.source_pages)
    from .company_extractor import is_company_identity_resolved
    if not is_company_identity_resolved(plan.company):
        add("Identity limitation", "Company identity remains unresolved in the retained identity evidence.")
    withheld = {w.code for w in result.validation_warnings}
    if "conflicting_values" in withheld:
        add("Source validation limit", "The analysis retains unresolved source-conflict warnings. Only validated selected evidence is shown; the original analysis records the remaining warnings.")
    if "presentation_closing_claim_withheld" in withheld or "presentation_topic_claims_withheld" in withheld:
        add("Interpretation limit", "Some proposed conclusions were withheld because their claims could not be supported within their own evidence scope.")
    if "presentation_topic_claim_withheld" in withheld:
        add("Interpretation limit", "Unsupported takeaways were replaced with analytical questions; the retained source values remain available.")
    if not any(items):
        return []
    add("Reading scope", "This presentation covers retained, source-validated evidence and does not represent every topic or table in the document. Original diagnostics remain in the analysis JSON.")
    return items


_DIRECT_ABSENCE = re.compile(
    r"(?i)\b(?:not|no|omit(?:s|ted)?|exclude(?:s|d)?)\b.{0,35}\b(?:display(?:ed)?|show(?:n)?|present(?:ed)?)\b"
    r"|\b(?:display(?:ed)?|show(?:n)?|present(?:ed)?)\b.{0,35}\b(?:not|no|omit(?:s|ted)?|exclude(?:s|d)?)\b"
)
_DETAIL_SCOPE = re.compile(r"(?i)\b(?:detail(?:ed|s)?|breakdown|supplier|vendor|customer|subcategor(?:y|ies))\b")
_PERIOD = re.compile(r"(?i)\b(?:FY\s*)?(?:19|20)\d{2}\b|\b(?:3|6|9|12)M\s*(?:19|20)\d{2}\b")


def _contradicted_by_retained_content(note, result) -> bool:
    """Drop an absence claim only when its named subject is visibly retained.

    This deliberately does not rewrite broad limitations.  It handles the
    narrow stale-plan case where a note says a category is not shown after the
    final plan/chart has retained that exact category.
    """
    if not _DIRECT_ABSENCE.search(note) or _DETAIL_SCOPE.search(note):
        return False
    plan = result.presentation_plan
    retained_ids = {
        identifier
        for slide in plan.slides
        for identifier in [*slide.observation_ids,
                           *(oid for block in slide.visual_blocks for oid in block.observation_ids)]
    }
    chart_ids = {identifier for slide in plan.slides for identifier in slide.chart_ids}
    retained_ids.update(oid for chart in result.charts if chart.id in chart_ids for oid in chart.observation_ids)
    normalized_note = " ".join(str(note).casefold().split())
    note_periods = {re.sub(r"\s+", "", match.group(0)).casefold() for match in _PERIOD.finditer(note)}
    for observation in result.observations:
        if observation.id not in retained_ids:
            continue
        if note_periods:
            observation_period = re.sub(r"\s+", "", observation.period or "").casefold()
            if observation_period not in note_periods:
                continue
        labels = [observation.metric_original, observation.metric_canonical or "",
                  *observation.category_dimensions.values()]
        for label in labels:
            subject = " ".join(str(label).casefold().split()).strip()
            if len(subject) >= 3 and re.search(rf"(?<!\w){re.escape(subject)}(?!\w)", normalized_note):
                return True
    return False
