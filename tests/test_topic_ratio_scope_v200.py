"""An unresolved ratio claim cannot discard unrelated selected topic evidence."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.agent.presentation_summary_selection import rebuild_selected_topic_summary
from adaptive_document_agent.agent.presentation_topic_scope_recovery import withheld_topic_ids
from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from tests.test_topic_scope_recovery_regressions import _synthetic_result, _assert_question_first


@pytest.mark.parametrize('compile_plan', [compile_topic_plan,
    lambda result: PresentationPlanRecovery().from_selected_topics(result)])
def test_unbound_ratio_withdraws_only_its_exact_topic_claim(compile_plan):
    result = _synthetic_result('metric_alias')
    topic = result.presentation_topics.topics[0]
    topic.takeaway = ('Loss for the year was reported across FY2023 to FY2025; '
                      'its ratio dipped in FY2024.')
    source = deepcopy((result.observations, result.presentation_topics, result.charts))
    probe = PresentationSlide(id='summary', title='Summary', slide_type='executive_summary',
        bullets=[topic.takeaway], observation_ids=[o.id for o in result.observations])
    issues = ClaimValidator().validate_slide(probe, result.observations)
    issue = next(i for i in issues if i.code == 'direction_ratio_subject_ambiguous')
    assert issue.slide_id == 'summary' and issue.bullet_index == 0
    assert issue.target_component == 'bullet'
    plan = compile_plan(result)
    _assert_question_first(result, plan)
    assert withheld_topic_ids(plan) == {'scope'}
    assert (result.observations, result.presentation_topics, result.charts) == source
    rebuild_selected_topic_summary(result, plan)
    _assert_question_first(result, plan)


def test_a_ratio_subject_error_without_a_unique_topic_owner_stays_blocked():
    from adaptive_document_agent.agent.presentation_topic_scope_recovery import recover_unscoped_topic_claims
    result = _synthetic_result('metric_alias')
    plan = compile_topic_plan(result)
    summary = next(s for s in plan.slides if s.slide_type == 'executive_summary')
    summary.bullets[0] = 'Reported figures changed; its ratio dipped in FY2024.'
    summary.bullet_observation_ids[0] = [o.id for o in result.observations[:2]]
    before = plan.model_copy(deep=True)
    issues = ClaimValidator().validate_plan(plan, result.observations, result.charts)
    assert any(i.code == 'direction_ratio_subject_ambiguous' for i in issues)
    assert not recover_unscoped_topic_claims(plan, result, issues)
    assert plan == before
