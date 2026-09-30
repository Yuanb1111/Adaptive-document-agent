"""Equivalent source-unit wording must not prevent proven duplicate alignment."""

import pytest

from adaptive_document_agent.models import ChartPlan, PresentationPlan
from adaptive_document_agent.validation.claim_validator import ClaimValidator, are_observations_compatible, repair_presentation_plan
from tests.test_presentation_evidence_alignment import _fact
from tests.test_segmented_direction_claims import _slide


def _case(component="message", metric="Loss for the year"):
    observations = [
        _fact(f"{context}_{year}", year, value, context=context, page=page).model_copy(update={
            "metric_original": metric, "metric_canonical": metric,
            "period": f"FY{year}", "period_type": "fiscal_year", "period_basis": "FY",
            "raw_unit": raw_unit, "ifrs_status": "IFRS",
        })
        for context, page, raw_unit in (("Statement", 407, "RMB"), ("Reconciliation", 409, "RMB in thousands"))
        for year, value in ((2022, -1567108), (2023, -1126683), (2024, -831501))
    ]
    slide = _slide(f"{metric} narrowed from FY2022 to FY2024.", observations, component)
    slide.source_pages = [407, 409]
    chart = ChartPlan(id="chart", title=metric, chart_type="line", question="How did this measure change?",
                      observation_ids=[item.id for item in observations[:3]], source_pages=[407])
    slide.chart_ids = [chart.id]
    return observations, PresentationPlan(title="Trajectory", slides=[slide]), chart


@pytest.mark.parametrize("component", ["title", "message", "bullets"])
def test_equivalent_unit_wording_aligns_repeated_annual_loss_rows(component):
    observations, plan, chart = _case(component)
    snapshot = [item.model_dump() for item in observations]
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])
    assert repairs
    assert repaired.slides[0].observation_ids == [item.id for item in observations[:3]]
    assert not ClaimValidator().validate_plan(repaired, observations, [chart])
    assert [item.model_dump() for item in observations] == snapshot
    assert not are_observations_compatible(observations[0], observations[-1])[0]
    assert not repair_presentation_plan(repaired, observations, [chart])[1]


@pytest.mark.parametrize("conflict", ["value", "unit_scale", "currency", "audited_status", "period_end", "ifrs_status"])
def test_unit_wording_does_not_hide_conflicting_values_or_scope(conflict):
    observations, plan, chart = _case()
    setattr(observations[-1], conflict, {
        "value": -831502000, "unit_scale": 1, "currency": "USD", "audited_status": "unaudited",
        "period_end": "2024-11-30", "ifrs_status": "ADJUSTED",
    }[conflict])
    original_ids = list(plan.slides[0].observation_ids)
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])
    assert not repairs
    assert repaired.slides[0].observation_ids == original_ids
    assert ClaimValidator().validate_plan(repaired, observations, [chart])


@pytest.mark.parametrize("scale", [None, 0])
def test_unknown_or_zero_scale_cannot_establish_equivalent_unit_wording(scale):
    observations, plan, chart = _case()
    for item in observations:
        item.unit_scale = scale
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])
    assert not repairs
    assert ClaimValidator().validate_plan(repaired, observations, [chart])


def test_nonfinancial_duplicate_series_uses_the_same_evidence_rule():
    observations, plan, chart = _case(metric="Service throughput")
    for item in observations:
        item.unit = "count"
        item.unit_family = "count"
        item.unit_scale = 1000
        item.value = abs(item.value)
    plan.slides[0].message = "Service throughput declined from FY2022 to FY2024."
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])
    assert repairs
    assert not ClaimValidator().validate_plan(repaired, observations, [chart])
