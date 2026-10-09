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
    retained.update(slide.theme_id for slide in plan.slides if slide.slide_type == 'analysis' and slide.theme_id)
    # A failed draft is not proof of absent source evidence. Use the final
    # renderer's exact input scopes when recovery produced unthemed pages.
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    from adaptive_document_agent.agent.topic_reference_binding import reference_aliases
    from adaptive_document_agent.agent.coverage_representation import representation_links
    lookup = None
    rendered_ids = {oid for record in result.presentation_export_trace for oid in record.get('observation_ids', [])}
    rendered = [item for item in result.observations if item.id in rendered_ids]
    by_id = {item.id: item for item in result.observations}
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
                if rendered_ids:
                    identifiers = topic.get('series_ids', [])
                    audited = draft.get('source_scopes', {})
                    if identifiers and all(sid in audited for sid in identifiers):
                        scopes = [[by_id[oid] for oid in audited[sid]]
                                  if audited[sid] and all(oid in by_id for oid in audited[sid]) else []
                                  for sid in identifiers]
                    else:
                        if lookup is None:
                            _, lookup = series_directory(result)
                        aliases = reference_aliases(lookup)
                        identifiers = [sid if sid in lookup else aliases.get(sid, sid) for sid in identifiers]
                        scopes = [lookup.get(sid, []) for sid in identifiers]
                    if scopes and all(scope and representation_links(scope, rendered) is not None for scope in scopes):
                        continue
                    if any(representation_links([item], rendered) is not None
                           for scope in scopes for item in scope):
                        add("Partially covered: " + topic.get("title", "Selected topic"),
                            "Some source evidence is shown, but the original topic was not retained in full. "
                            "See the analysis audit for the remaining evidence scope.")
                        continue
                add("Not covered: " + topic.get("title", "Selected topic"),
                    "This topic was not retained as a validated finding; its source evidence and draft remain in the analysis audit.")
    for note in plan.coverage_notes:
        if not _editorial_omission(note, result) and not _contradicted_by_retained_content(note, result):
            add("Coverage boundary", note)
    first_pages = {}
    for slide in plan.slides:
        if slide.slide_type == "analysis" and slide.theme_id:
            first_pages.setdefault(slide.theme_id, slide)
    displayed_themes = {theme_id for theme_id, slide in first_pages.items()
                        if not any(block.role in {"horizon", "waterfall"} for block in slide.visual_blocks)}
    for theme in plan.themes:
        if theme.id in displayed_themes:
            # These accompany the corresponding visual, where a reader can
            # interpret the measure without hunting through a scope appendix.
            continue
        for caveat in theme.caveats:
            add(theme.title, caveat, theme.source_pages)
    from .company_extractor import is_company_identity_resolved
    if not is_company_identity_resolved(plan.company):
        add("Identity limitation", "Company identity remains unresolved in the retained identity evidence.")
    withheld = {w.code for w in result.validation_warnings}
    if "conflicting_values" in withheld:
        add("Source validation limit", "The analysis retains unresolved source-conflict warnings. Only validated selected evidence is shown; the original analysis records the remaining warnings.")
    # Rejected draft wording is an internal validation event, not a source
    # limitation. Claim-withheld diagnostics remain in scope_audit_notes; real
    # coverage boundaries, missing topics and source conflicts stay visible.
    if not any(items):
        return []
    return items


def _editorial_omission(note, result):
    """Selection priorities are audit data, not source-data limitations."""
    selection = result.presentation_topics
    if selection and any(note.endswith(": " + item.reason) for item in selection.omissions):
        return True
    return bool(re.search(r"(?i)\b(?:secondary|redundant|weaker relevance|already explained|"
                          r"omitted to (?:keep|avoid)|does not directly answer)\b", note))


def scope_audit_notes(result):
    plan = result.presentation_plan
    if plan is None:
        return ""
    return json.dumps({"coverage_notes": plan.coverage_notes,
                       "theme_caveats": {theme.id: theme.caveats for theme in plan.themes},
                       "validation_warnings": [issue.model_dump(mode="json")
                                               for issue in result.validation_warnings]},
                      ensure_ascii=False)


_ABSENCE_STATEMENT = re.compile(
    r"(?ix)^\s*(?:the\s+)?(?P<subject>[^.;:]+?)(?:\s+category)?\s+"
    r"(?:is|was)\s+not\s+(?:shown|displayed|presented)"
    r"(?:\s+for\s+(?P<period>(?:FY\s*)?(?:19|20)\d{2}|(?:3|6|9|12)M\s*(?:19|20)\d{2}))?\s*[.]?\s*$"
)
_DETAIL_SCOPE = re.compile(r"(?i)\b(?:detail(?:ed|s)?|breakdown|supplier|vendor|customer|subcategor(?:y|ies))\b")


def _contradicted_by_retained_content(note, result) -> bool:
    """Drop an absence claim only when its named subject is visibly retained.

    This deliberately does not rewrite broad limitations.  It handles the
    narrow stale-plan case where a note says a category is not shown after the
    final plan/chart has retained that exact category.
    """
    statement = _ABSENCE_STATEMENT.fullmatch(note)
    if statement is None or _DETAIL_SCOPE.search(note):
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
    subject = " ".join(statement['subject'].casefold().split())
    note_period = re.sub(r"\s+", "", statement['period'] or "").casefold()
    for observation in result.observations:
        if observation.id not in retained_ids:
            continue
        if note_period:
            observation_period = re.sub(r"\s+", "", observation.period or "").casefold()
            if observation_period != note_period:
                continue
        labels = [observation.metric_original, observation.metric_canonical or "",
                  *observation.category_dimensions.values()]
        for label in labels:
            retained_subject = " ".join(str(label).casefold().split()).strip()
            if len(retained_subject) >= 3 and retained_subject == subject:
                return True
    return False
