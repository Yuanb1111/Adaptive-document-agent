"""Ambiguous questions cannot veto other topics or silently reverse offset claims."""
import json

from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
from adaptive_document_agent.agent.presentation_summary_selection import rebuild_selected_topic_summary
from adaptive_document_agent.services.presentation_claim_evidence import prepare_presentation_claims
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from adaptive_document_agent.models import PresentationPlan
from tests.test_segmented_direction_claims import _series, _slide
from tests.test_topic_scope_recovery_regressions import _synthetic_result, _analysis, _SOURCE_FIELDS


def test_ambiguous_question_is_withdrawn_without_losing_other_selected_topics():
    result = _synthetic_result('metric_alias')
    topic = result.presentation_topics.topics[0]
    topic.question = 'Did loss for the year widen from FY2023 to FY2025?'
    raw = result.model_dump(include=_SOURCE_FIELDS)
    result.presentation_plan = compile_topic_plan(result)
    plan = result.presentation_plan
    assert {t.id for t in plan.themes} == {'scope', 'volume'}
    assert _analysis(plan).title == _analysis(plan).message == 'How do the cited measures compare?'
    assert _analysis(plan, 'volume').title == result.presentation_topics.topics[1].takeaway
    audit = [json.loads(note.split(' ', 1)[1]) for note in plan.editorial_notes
             if note.startswith('[claim_scope_withheld] ')]
    assert any(record['question'] == topic.question for record in audit)
    assert not ClaimValidator().validate_plan(plan, result.observations, result.charts)
    PresentationPlanValidator().validate(plan, result)
    for _ in range(2):
        prepare_presentation_claims(result)
        assert not PresentationPlanRecovery().recover_missing_plan(result)
        assert not ClaimValidator().validate_plan(plan, result.observations, result.charts)
    assert result.model_dump(include=_SOURCE_FIELDS) == raw
    # The original unsafe wording still fails the unchanged claim gate.
    original = plan.model_copy(deep=True)
    _analysis(original).title = topic.question
    assert any(i.code == 'direction_scope_ambiguous' for i in
               ClaimValidator().validate_plan(original, result.observations, result.charts))


def test_offset_object_never_borrows_the_counterbalancing_subjects_values():
    observations = _series('Northern sales', [10, 20, 30]) + _series('Other sales', [40, 30, 20])
    text = 'Northern sales offset unclassified region declines from FY2023 to FY2025.'
    slide = _slide(text, observations, 'title')
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(i.code == 'direction_scope_ambiguous' for i in issues)
    assert not any(i.code == 'directional_contradiction' for i in issues)
    repaired, _ = repair_presentation_plan(PresentationPlan(title='Review', slides=[slide]), observations)
    assert repaired.slides[0].title == text


def test_withdrawn_question_stays_withdrawn_when_overview_is_absent():
    result = _synthetic_result('metric_alias')
    result.presentation_topics.topics[0].question = 'Did loss for the year widen from FY2023 to FY2025?'
    result.presentation_plan = compile_topic_plan(result)
    plan = result.presentation_plan
    plan.slides = [slide for slide in plan.slides
                   if not (slide.slide_type == 'analysis' and slide.theme_id == 'scope')]
    assert rebuild_selected_topic_summary(result, plan)
    summary = next(slide for slide in plan.slides if slide.slide_type == 'executive_summary')
    assert summary.bullets[0] == 'How do the cited measures compare?'
    assert not ClaimValidator().validate_plan(plan, result.observations, result.charts)


def test_offset_independent_named_predicates_keep_their_own_subjects():
    observations = _series('Capacity', [10, 20, 30]) + _series('Demand', [40, 30, 20])
    slide = _slide('Capacity increased from FY2023 to FY2025, offset by Demand declines from FY2023 to FY2025.',
                   observations, 'title')
    assert not ClaimValidator().validate_slide(slide, observations)
