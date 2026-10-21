"""Retain selected questions when a takeaway cannot bind to unique evidence."""

import json

from adaptive_document_agent.models import PipelineResult, PresentationPlan, ValidationIssue
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan
from adaptive_document_agent.validation.presentation_provenance import insight_inputs

_WITHHELD_PREFIX = "[claim_scope_withheld] "


def withheld_topic_ids(plan: PresentationPlan) -> set[str]:
    """Read durable audit markers so later summary rebuilds cannot revive a claim."""
    identifiers = set()
    for note in plan.editorial_notes:
        if not note.startswith(_WITHHELD_PREFIX):
            continue
        try:
            entry = json.loads(note[len(_WITHHELD_PREFIX):])
        except (TypeError, ValueError):
            continue
        if isinstance(entry, dict) and isinstance(entry.get("topic_id"), str):
            identifiers.add(entry["topic_id"])
    return identifiers


def withheld_display_questions(plan: PresentationPlan) -> dict[str, str]:
    """Keep a checked neutral prompt durable when its overview is later absent."""
    questions = {}
    for note in plan.editorial_notes:
        if note.startswith(_WITHHELD_PREFIX):
            try:
                record = json.loads(note[len(_WITHHELD_PREFIX):])
            except (TypeError, ValueError):
                continue
            if (isinstance(record, dict) and isinstance(record.get('topic_id'), str)
                    and isinstance(record.get('display_question'), str)):
                questions[record.get('topic_id')] = record['display_question']
    return questions


def recover_cached_topic_claims(plan: PresentationPlan, result: PipelineResult) -> list[str]:
    """Apply the compiler's ambiguity boundary to an already retained topic plan.

    Source-bound share preparation can legitimately restore cached wording,
    but that copy still needs the strict metric/category scope checks. Only
    the retained plan is eligible; in-progress compilation keeps its existing
    explicit validation boundary. Contradictions and other errors stay blocked.
    """
    if (plan is not result.presentation_plan or not result.presentation_topics
            or plan.planning_origin not in {"topic_compilation", "topic_recovery"}):
        return []
    issues = ClaimValidator().validate_plan(plan, result.observations, result.charts,
                                           insight_observation_ids=insight_inputs(result))
    if not any(issue.code == "direction_scope_ambiguous" for issue in issues):
        return []
    return recover_unscoped_topic_claims(plan, result, issues)


def validate_selected_topic_claims(plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
    """Use one strict claim-recovery boundary for compiled and fallback topics."""
    refs = insight_inputs(result)
    plan, repairs = repair_presentation_plan(plan, result.observations, result.charts,
                                            insight_observation_ids=refs)
    validator = ClaimValidator()
    problems = validator.validate_plan(plan, result.observations, result.charts,
                                       insight_observation_ids=refs)
    if problems:
        repairs.extend(recover_unscoped_topic_claims(plan, result, problems))
        problems = validator.validate_plan(plan, result.observations, result.charts,
                                           insight_observation_ids=refs)
    if problems:
        raise ValueError("Selected topic claims failed validation: " + "; ".join(p.message for p in problems))
    plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *repairs]))
    return plan


def _summary_topic_bindings(plan: PresentationPlan, result: PipelineResult) -> dict[str, list[str | None]]:
    """Bind repaired summary copy through complete, uniquely owned evidence.

    Prose may already have a validated deterministic correction. A partial or
    mixed evidence set cannot identify its topic merely by position or wording.
    Exact corroborating records may stand for one another, as in normal source
    alignment; both directions must preserve the entire selected fact scope.
    """
    from .coverage_representation import representation_links

    topics = {topic.id: topic for topic in result.presentation_topics.topics}
    observations = {item.id: item for item in result.observations}
    charts = {chart.id: chart for chart in result.charts}
    scopes = {}
    for theme in plan.themes:
        if theme.id not in topics:
            continue
        ids = set(theme.observation_ids)
        ids.update(oid for cid in theme.chart_ids if cid in charts
                   for oid in [*charts[cid].observation_ids, *charts[cid].total_observation_ids])
        ids = {oid for oid in ids if oid in observations and observations[oid].evidence
               and observations[oid].validation_status in {"valid", "partially_valid"}}
        if ids:
            scopes[theme.id] = ids

    def same_scope(left, right):
        if not left or not right or not left <= observations.keys():
            return False
        if left == right:
            return True
        a, b = [observations[oid] for oid in left], [observations[oid] for oid in right]
        return representation_links(a, b) is not None and representation_links(b, a) is not None

    bindings = {}
    for summary in plan.slides:
        if summary.slide_type not in {"summary", "executive_summary"}:
            continue
        owners = [None] * len(summary.bullets)
        if len(summary.bullet_observation_ids) == len(summary.bullets):
            for index, (text, ids) in enumerate(zip(summary.bullets, summary.bullet_observation_ids)):
                matches = [topic_id for topic_id, scope in scopes.items() if same_scope(set(ids), scope)]
                if len(matches) > 1:
                    matches = [topic_id for topic_id in matches if text in {
                        topics[topic_id].takeaway, topics[topic_id].title, topics[topic_id].question}]
                if len(matches) == 1:
                    owners[index] = matches[0]
        bindings[summary.id] = owners
    return bindings


def recover_unscoped_topic_claims(plan: PresentationPlan, result: PipelineResult,
                                 issues: list[ValidationIssue]) -> list[str]:
    """Withdraw unresolved metric, category or period assertions to the same question.

    This does not choose missing endpoints or alter the model's selected data.
    A candidate must remove errors without adding any other validation error.
    The authored takeaway remains in the raw topic and in an audit note.
    """
    if not result.presentation_topics:
        return []
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

    topics = {topic.id: topic for topic in result.presentation_topics.topics}
    summaries = {slide.id: slide for slide in plan.slides if slide.slide_type in {"summary", "executive_summary"}}
    summary_owners = _summary_topic_bindings(plan, result)
    by_id = {item.id: item for item in result.observations}
    affected = set()
    errors_by_topic: dict[str, list[str]] = {}
    for issue in issues:
        if issue.code != "direction_scope_ambiguous":
            continue
        slide_id = getattr(issue, "slide_id", None)
        summary = summaries.get(slide_id)
        matched = []
        if summary:
            index = getattr(issue, "bullet_index", None)
            if index is not None and 0 <= index < len(summary.bullets):
                owner = summary_owners[summary.id][index]
                if owner is not None:
                    if issue.related_ids:
                        from .coverage_representation import representation_links
                        ids = summary.bullet_observation_ids[index]
                        if (any(oid not in by_id for oid in [*issue.related_ids, *ids])
                                or representation_links([by_id[oid] for oid in issue.related_ids],
                                                        [by_id[oid] for oid in ids]) is None):
                            continue
                    matched = [owner]
        else:
            matched = [slide.theme_id for slide in plan.slides if slide.id == slide_id]
        for topic_id in matched:
            if topic_id not in topics:
                continue
            affected.add(topic_id)
            errors_by_topic.setdefault(topic_id, []).append(issue.message)
    # A separate scoped-value gate may find an endpoint attributed to a
    # differently named source measure. Withdraw those authored takeaways in
    # the same transaction; otherwise they prevent unrelated scope repairs.
    from adaptive_document_agent.validation.scoped_narrative_values import scoped_value_errors
    from adaptive_document_agent.models import PresentationSlide
    from adaptive_document_agent.validation.narrative_plan_validator import expanded_observation_ids
    charts = {item.id: item for item in result.charts}
    for slide in plan.slides:
        if slide.slide_type == "analysis" and slide.theme_id in topics:
            copies = [(slide.theme_id, slide.title, expanded_observation_ids(slide, charts))]
        elif slide.id in summaries:
            copies = [(topic_id, slide.bullets[index], slide.bullet_observation_ids[index])
                      for index, topic_id in enumerate(summary_owners[slide.id]) if topic_id is not None]
        else:
            continue
        for topic_id, text, ids in copies:
            records = [by_id[oid] for oid in ids if oid in by_id]
            view = PresentationSlide(id=slide.id, slide_type=slide.slide_type, title=text)
            errors = scoped_value_errors(view, records, result.observations)
            if errors:
                affected.add(topic_id)
                errors_by_topic.setdefault(topic_id, []).extend(errors)
    if not affected:
        return []
    candidate = plan.model_copy(deep=True)
    notes = []
    for slide in candidate.slides:
        if slide.slide_type != "analysis" or slide.theme_id not in affected or slide.theme_id not in topics:
            continue
        question = slide.analytical_question.strip()
        if not question:
            continue
        notes.append(f"Slide {slide.id}: retained selected question because the takeaway lacked uniquely bound evidence. "
                     f"Authored takeaway: {topics[slide.theme_id].takeaway}")
        candidate.editorial_notes.append(_WITHHELD_PREFIX + json.dumps({
            "topic_id": slide.theme_id,
            "takeaway": topics[slide.theme_id].takeaway,
            "question": slide.analytical_question,
            "errors": list(dict.fromkeys(errors_by_topic[slide.theme_id])),
            "withdrawn_summary_copy": [
                {"slide_id": summary.id, "bullet_index": index, "text": summary.bullets[index],
                 "observation_ids": list(summary.bullet_observation_ids[index])}
                for summary in summaries.values() for index, owner in enumerate(summary_owners[summary.id])
                if owner == slide.theme_id
            ],
        }, ensure_ascii=False, sort_keys=True))
        slide.title = question
        slide.message = question
        # These headings are also rendered by the contents, narrow-layout
        # fallback and appendix. A withdrawn takeaway cannot survive there as
        # an unchecked section label when the full question is too long.
        slide.section_title = question
        theme = next((t for t in candidate.themes if t.id == slide.theme_id), None)
        if theme:
            theme.title = question
    # Change only bullets proved to belong to an affected topic. Rebuilding a
    # whole summary could reorder bullets, widen their evidence, or revive an
    # unrelated claim that already received its own validated correction.
    questions = {slide.theme_id: slide.analytical_question for slide in candidate.slides
                 if slide.slide_type == "analysis" and slide.theme_id in affected
                 and slide.analytical_question.strip()}
    for summary in candidate.slides:
        if summary.id not in summary_owners:
            continue
        for index, owner in enumerate(summary_owners[summary.id]):
            if owner in questions:
                summary.bullets[index] = questions[owner]
    # Cached summaries can still carry exact repeated-source records. Reapply
    # normal provenance alignment before comparing the candidate's errors;
    # this never merges conflicting values or relaxes the no-new-errors gate.
    from adaptive_document_agent.validation.presentation_evidence_alignment import align_redundant_slide_evidence
    notes.extend(align_redundant_slide_evidence(candidate, result.observations, result.charts))
    checked = ClaimValidator().validate_plan(candidate, result.observations, result.charts,
                                            insight_observation_ids=insight_inputs(result))
    # An authored question can itself presuppose an unbound movement (for
    # example, improvement "after deterioration" without comparison endpoints).
    # Repeating it in the title and summary creates fresh errors and used to
    # veto recovery for every other selected topic as well. Withdraw only that
    # ambiguous question to a neutral display prompt; keep its exact original
    # wording in the topic and audit, and retain all selected source records.
    question_topics = set()
    for issue in checked:
        if issue.code != 'direction_scope_ambiguous':
            continue
        slide = next((s for s in candidate.slides if s.id == getattr(issue, 'slide_id', None)), None)
        if slide is None:
            continue
        owner = slide.theme_id
        if slide.id in summary_owners:
            index = getattr(issue, 'bullet_index', None)
            owner = (summary_owners[slide.id][index] if index is not None
                     and 0 <= index < len(summary_owners[slide.id]) else None)
        if owner in affected:
            question_topics.add(owner)
    if question_topics:
        neutral = 'How do the cited measures compare?'
        for slide in candidate.slides:
            if slide.slide_type == 'analysis' and slide.theme_id in question_topics:
                slide.title = slide.message = slide.section_title = slide.analytical_question = neutral
            if slide.id in summary_owners:
                for index, owner in enumerate(summary_owners[slide.id]):
                    if owner in question_topics:
                        slide.bullets[index] = neutral
        for theme in candidate.themes:
            if theme.id in question_topics:
                theme.title = neutral
        for owner in sorted(question_topics):
            notes.append(f'Topic {owner}: withheld an ambiguously scoped question from display; '
                         f'original question: {topics[owner].question}')
        for index, note in enumerate(candidate.editorial_notes):
            if note.startswith(_WITHHELD_PREFIX):
                try:
                    record = json.loads(note[len(_WITHHELD_PREFIX):])
                except (TypeError, ValueError):
                    continue
                if isinstance(record, dict) and record.get('topic_id') in question_topics:
                    record['display_question'] = neutral
                    candidate.editorial_notes[index] = _WITHHELD_PREFIX + json.dumps(record, ensure_ascii=False, sort_keys=True)
        checked = ClaimValidator().validate_plan(candidate, result.observations, result.charts,
                                                insight_observation_ids=insight_inputs(result))
    key = lambda issue: (issue.code, issue.message, getattr(issue, "slide_id", None),
                         getattr(issue, "target_component", None), getattr(issue, "bullet_index", None))
    if len(checked) >= len(issues) or not {key(issue) for issue in checked} <= {key(issue) for issue in issues}:
        return []
    try:
        PresentationPlanValidator().validate(candidate, result)
    except ValueError:
        return []  # A question is not an exemption from number, source or scope checks.
    plan.slides = candidate.slides
    plan.themes = candidate.themes
    plan.editorial_notes = list(dict.fromkeys(candidate.editorial_notes))
    plan.editorial_status = "needs_review"
    for topic_id in sorted(withheld_topic_ids(candidate)):
        warning = ValidationIssue(
            code="presentation_topic_claims_withheld", severity="warning", stage="presentation",
            related_ids=[topic_id],
            message="Retained the model-selected question and evidence scope; an ambiguously bound takeaway "
                    "was withheld. Original wording and validation errors remain in the presentation audit.",
        )
        if not any(issue == warning for issue in result.validation_warnings):
            result.validation_warnings.append(warning)
    return notes
