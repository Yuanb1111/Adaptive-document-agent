"""Editable topic inventory and measured allocation, without choosing importance."""
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adaptive_document_agent.models import PresentationTopicSelection
from adaptive_document_agent.models.presentation import PresentationTopic


class BudgetTopic(PresentationTopic):
    model_config = ConfigDict(extra='forbid')

    @model_validator(mode='before')
    @classmethod
    def existing_topic(cls, value):
        if isinstance(value, PresentationTopic):
            return value.model_dump()
        return value


class BudgetSeriesDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    series_id: str
    include: bool
    reason: str = Field(min_length=1, max_length=500)


class PhysicalBudgetSelection(BaseModel):
    """Only current topics and their exact editable series ledger are writable."""
    model_config = ConfigDict(extra='forbid')
    decisions: list[BudgetSeriesDecision]
    topics: list[BudgetTopic] = Field(min_length=1, max_length=8)


def editable_series_inventory(original):
    owners = {}
    for topic in original.topics:
        for series_id in topic.series_ids:
            owners.setdefault(series_id, []).append(topic.id)
    return [dict(series_id=series_id, original_topic_ids=topic_ids)
            for series_id, topic_ids in owners.items()]


def selection_inventory_diagnostics(draft, original):
    """Report exact address defects; no source meaning or importance is inferred."""
    old = {topic.id: topic for topic in original.topics}
    wanted = {row['series_id'] for row in editable_series_inventory(original)}
    ids = [decision.series_id for decision in draft.decisions]
    selected = {series_id for topic in draft.topics for series_id in topic.series_ids}
    included = {decision.series_id for decision in draft.decisions if decision.include}
    topic_ids = [topic.id for topic in draft.topics]
    return dict(expected_decision_count=len(wanted), actual_decision_count=len(ids),
        missing_series_ids=sorted(wanted-set(ids)), extra_series_ids=sorted(set(ids)-wanted),
        duplicate_series_ids=sorted(key for key, count in Counter(ids).items() if count > 1),
        included_but_unselected_series_ids=sorted(included-selected),
        selected_but_not_included_series_ids=sorted(selected-included),
        blank_reason_series_ids=sorted(decision.series_id for decision in draft.decisions if not decision.reason.strip()),
        unknown_topic_ids=sorted(set(topic_ids)-set(old)),
        duplicate_topic_ids=sorted(key for key, count in Counter(topic_ids).items() if count > 1),
        empty_topic_ids=[topic.id for topic in draft.topics if not topic.series_ids],
        moved_or_unknown_topic_series=[dict(topic_id=topic.id,
            series_ids=sorted(set(topic.series_ids)-set(old[topic.id].series_ids)))
            for topic in draft.topics if topic.id in old and not set(topic.series_ids) <= set(old[topic.id].series_ids)],
        duplicate_topic_series=[dict(topic_id=topic.id, series_ids=sorted(
            key for key, count in Counter(topic.series_ids).items() if count > 1))
            for topic in draft.topics if len(set(topic.series_ids)) != len(topic.series_ids)],
        no_topics=not draft.topics)


def invalid_inventory(diagnostics):
    return any(value for key, value in diagnostics.items()
               if key not in {'expected_decision_count', 'actual_decision_count'})


def canonical_budget_selection(draft, original):
    """Keep the historical bounded display list; complete new decisions stay audited.

    The canonical omissions field is not the complete budget decision ledger.
    Every editable include/omit decision and reason remains in the full proposal
    reviewed independently and retained in the budget success/failure audit.
    """
    return PresentationTopicSelection(topics=[PresentationTopic.model_validate(topic.model_dump())
        for topic in draft.topics], omissions=[item.model_copy(deep=True) for item in original.omissions])


def measured_budget_allocation(counts, requirement, requirements, *, maximum_analysis_slides):
    """Explain current native costs; final export remains the authoritative gate."""
    caps = [item for item in requirements.items if item.kind == 'slide_limit'
            and item.resolution == 'resolved' and item.slide_section == 'report'
            and item.max_slides is not None] if requirements else []
    if not caps:
        caps = [requirement]
    constraints = []
    for cap in caps:
        measured = counts['total' if cap.slide_scope == 'all' else 'body']
        other = measured-counts['analysis']
        constraints.append(dict(slide_scope=cap.slide_scope, maximum_slides=cap.max_slides,
            measured_slides=measured, over_budget_by=max(0, measured-cap.max_slides),
            current_non_analysis_slides=other,
            analysis_capacity_with_current_other_pages=max(0, cap.max_slides-other)))
    current = counts['total' if requirement.slide_scope == 'all' else 'body']
    return dict(basis='Measured current native deck; a fresh briefing can change overhead. Final native export checks remain mandatory.',
        slide_scope=requirement.slide_scope, current_scope_slides=current,
        current_introduction_slides=counts['introduction'], current_analysis_slides=counts['analysis'],
        current_non_intro_non_analysis_slides=current-counts['introduction']-counts['analysis'],
        maximum_analysis_slides=maximum_analysis_slides, constraints=constraints,
        effective_analysis_capacity=max(0, min([maximum_analysis_slides] + [
            item['analysis_capacity_with_current_other_pages'] for item in constraints])))


def budget_action_feedback(counts, allocation):
    """Expose the measured repair task and the actual subset-only action space."""
    return dict(current_analysis_slides=counts['analysis'],
        analysis_capacity_with_current_overhead=allocation['effective_analysis_capacity'],
        required_analysis_slide_reduction=max(0, counts['analysis']-allocation['effective_analysis_capacity']),
        report_constraints=allocation['constraints'], measured_original_topic_costs=counts.get('topic_pages', []),
        measured_native_groups=counts.get('native_groups', []),
        supported_actions=['Omit an entire lower-priority original topic with explicit source-aware series decisions.',
            'Retain an original topic ID with a subset of only its own original series; rewrite copy to that exact scope.'],
        unsupported_action='Cross-topic evidence unions are not supported. A topic cannot take another original topic\'s series.',
        copy_only_warning='Rewording titles or questions does not remove any selected chart series. Resolve the measured excess through model-owned scope/priority decisions; do not echo the full original selection.',
        inability='If no honest fitting subset exists, retain the indispensable evidence and explain that inability in its decision reasons. Never invent omission reasons; the candidate must then fail transparently.',
        authority='Current measured costs define the repair task; final native checks remain mandatory. Python chooses no omissions.')
