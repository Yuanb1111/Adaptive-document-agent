"""A repaired summary keeps topic ownership through complete evidence scopes."""

import json

import pytest

from adaptive_document_agent.agent.presentation_topic_scope_recovery import (
    recover_unscoped_topic_claims, withheld_topic_ids,
)
from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
from adaptive_document_agent.models import ChartPlan, PresentationTopic, PresentationTopicSelection
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_segmented_direction_claims import _series
from tests.test_topic_scope_recovery_regressions import _synthetic_result


_SOURCE={"observations","charts","presentation_topics","analysis_results","insights","llm_usage"}


def result_for_repaired_cash_claim():
    result=_synthetic_result("metric_alias")
    groups=[_series("Net cash from/(used in) operating activities",[12,-34,-56]),
            _series("Working capital changes",[21,-19,-18]),
            _series("Operating loss before changes in working capital",[-14,-7,-10])]
    volume=[o for o in result.observations if o.metric_original=="Units"]
    groups.append(volume)
    for group in groups:
        for obs in group:
            obs.metric_canonical=obs.metric_original
            obs.evidence[0].row_label=obs.metric_original
    result.observations=[o for group in groups for o in group]
    result.charts=[ChartPlan(id=f"chart_{index}",title=group[0].metric_original,
        chart_type="line",available_chart_types=["line","bar","table"],
        question="How did the reported measures compare?",observation_ids=[o.id for o in group],
        source_pages=[8],x_axis_title="Period",y_axis_title=group[0].raw_unit)
        for index,group in enumerate(groups)]
    _,lookup=series_directory(result)
    selected={o.id for group in groups[:-1] for o in group}
    topic=PresentationTopic(id="cash_loss",title="Operating cash flow and loss measures",
        question="How did operating cash flow, working capital changes, and operating loss compare across fiscal years?",
        rationale="Retain the distinct annual measures and their complete source evidence.",
        takeaway="Operating cash outflow increased from FY2023 to FY2025; pre-working-capital operating loss narrowed then worsened in FY2025.",
        series_ids=[sid for sid,items in lookup.items() if {o.id for o in items}<=selected])
    other=result.presentation_topics.topics[1].model_copy(deep=True)
    other.series_ids=[sid for sid,items in lookup.items() if {o.id for o in items}=={o.id for o in volume}]
    result.presentation_topics=PresentationTopicSelection(topics=[topic,other])
    return result


def summary(plan):
    return next(slide for slide in plan.slides if slide.slide_type=="executive_summary")


def repaired_checkpoint():
    result=result_for_repaired_cash_claim()
    seed=result.model_copy(deep=True)
    seed.presentation_topics.topics[0].takeaway=seed.presentation_topics.topics[0].question
    plan=compile_topic_plan(seed)
    # This is the already validated cash-claim correction that precedes scope
    # recovery; the unresolved loss clause still needs an exact question fallback.
    summary(plan).bullets[0]=result.presentation_topics.topics[0].takeaway.replace("increased","turned negative",1)
    issues=ClaimValidator().validate_plan(plan,result.observations,result.charts)
    assert len(issues)==1 and issues[0].code=="direction_scope_ambiguous"
    return result,plan,issues


def test_compilation_retains_question_after_another_claim_in_same_bullet_was_repaired():
    result=result_for_repaired_cash_claim()
    original=result.model_dump(include=_SOURCE)
    plan=compile_topic_plan(result)
    topic,other=result.presentation_topics.topics
    assert withheld_topic_ids(plan)=={topic.id}
    assert summary(plan).bullets==[topic.question,other.takeaway]
    assert len(plan.themes)==2
    assert not ClaimValidator().validate_plan(plan,result.observations,result.charts)
    PresentationPlanValidator().validate(plan,result)
    marker=json.loads(next(note for note in plan.editorial_notes if note.startswith("[claim_scope_withheld] ")).split(" ",1)[1])
    assert marker["takeaway"]==topic.takeaway
    assert "turned negative" in marker["withdrawn_summary_copy"][0]["text"]
    assert "narrowed then worsened" in marker["withdrawn_summary_copy"][0]["text"]
    assert result.model_dump(include=_SOURCE)==original


def test_reordered_summary_keeps_unrelated_approved_copy_and_exact_citations():
    result,plan,issues=repaired_checkpoint()
    sl=summary(plan)
    sl.bullets.reverse();sl.bullet_observation_ids.reverse()
    sl.bullets[0]="Units increased from FY2023 to FY2025."
    original_ids=[list(ids) for ids in sl.bullet_observation_ids]
    original=result.model_dump(include=_SOURCE)
    issues=ClaimValidator().validate_plan(plan,result.observations,result.charts)
    assert recover_unscoped_topic_claims(plan,result,issues)
    assert summary(plan).bullets==["Units increased from FY2023 to FY2025.",result.presentation_topics.topics[0].question]
    assert summary(plan).bullet_observation_ids==original_ids
    assert not ClaimValidator().validate_plan(plan,result.observations,result.charts)
    PresentationPlanValidator().validate(plan,result)
    assert result.model_dump(include=_SOURCE)==original


@pytest.mark.parametrize("corruption",["partial","mixed","unknown","wrong_topic","missing_bindings"])
def test_unproved_or_corrupted_evidence_binding_cannot_withdraw_a_different_topic(corruption):
    result,plan,issues=repaired_checkpoint()
    sl=summary(plan)
    if corruption=="partial":sl.bullet_observation_ids[0].pop()
    elif corruption=="mixed":sl.bullet_observation_ids[0].append(sl.bullet_observation_ids[1][0])
    elif corruption=="unknown":sl.bullet_observation_ids[0].append("unavailable_source")
    elif corruption=="wrong_topic":sl.bullet_observation_ids[0]=list(sl.bullet_observation_ids[1])
    else:sl.bullet_observation_ids=[]
    before=plan.model_dump()
    assert recover_unscoped_topic_claims(plan,result,issues)==[]
    assert plan.model_dump()==before
    assert not withheld_topic_ids(plan)


def test_identical_topic_scopes_cannot_guess_ownership_from_repaired_copy():
    result,plan,issues=repaired_checkpoint()
    topic=result.presentation_topics.topics[0]
    second=topic.model_copy(deep=True,update={"id":"different_question","title":"Independent review",
        "question":"What explains the separately selected operating measures?","takeaway":"Separate selected finding."})
    result.presentation_topics.topics.append(second)
    duplicate=next(theme for theme in plan.themes if theme.id==topic.id).model_copy(
        deep=True,update={"id":second.id,"title":second.title,"question":second.question})
    plan.themes.append(duplicate)
    before=plan.model_dump()
    assert recover_unscoped_topic_claims(plan,result,issues)==[]
    assert plan.model_dump()==before


def test_out_of_bounds_issue_index_cannot_select_the_last_summary_bullet():
    result,plan,issues=repaired_checkpoint()
    issues[0].bullet_index=-1
    before=plan.model_dump()
    assert recover_unscoped_topic_claims(plan,result,issues)==[]
    assert plan.model_dump()==before
