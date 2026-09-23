"""Duplicate financial facts must not cross-wire a slide's plotted series."""

from adaptive_document_agent.models import (
    ChartPlan, Observation, PresentationPlan, PresentationSlide,
    PresentationVisualBlock, SourceEvidence,
)
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan


def _fact(identifier: str, year: int, value: int, *, context: str, page: int) -> Observation:
    return Observation(
        id=identifier,
        metric_original="Inventories",
        value=float(value) * 1000,
        raw_value=f"{value:,}",
        unit="currency",
        raw_unit="RMB '000",
        unit_scale=1000,
        unit_family="currency",
        currency="RMB",
        period=f"{year}-12-31",
        period_type="balance_sheet_date",
        dimensions={"column_role": "amount", "table_context": context},
        evidence=[SourceEvidence(page=page, text=f"{value:,}", extraction_method="digital_table", confidence=0.9)],
        confidence=0.9,
    )


def _plan_and_chart() -> tuple[PresentationPlan, ChartPlan]:
    chart = ChartPlan(
        id="inventory_chart",
        title="Inventories",
        chart_type="bar",
        question="How did inventories change?",
        observation_ids=["chart_2023", "chart_2024", "chart_2025"],
        source_pages=[253],
    )
    plan = PresentationPlan(
        title="Working capital",
        slides=[PresentationSlide(
            id="working_capital",
            slide_type="analysis",
            title="Inventories increased from 2023-12-31 to 2025-12-31",
            chart_ids=[chart.id],
            observation_ids=["other_2023", "other_2024", "other_2025"],
            source_pages=[238, 253],
        )],
    )
    return plan, chart


def test_repair_aligns_exact_multi_period_duplicates_with_chart_source() -> None:
    plan, chart = _plan_and_chart()
    observations = [
        *[_fact(f"other_{year}", year, value, context="FINANCIAL INFORMATION", page=238)
          for year, value in [(2023, 120578), (2024, 139486), (2025, 244691)]],
        *[_fact(f"chart_{year}", year, value, context="CURRENT ASSETS/LIABILITIES", page=253)
          for year, value in [(2023, 120578), (2024, 139486), (2025, 244691)]],
    ]

    assert any(issue.code == "directional_contradiction" for issue in ClaimValidator().validate_plan(plan, observations, [chart]))
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])

    assert repaired.slides[0].observation_ids == ["chart_2023", "chart_2024", "chart_2025"]
    assert repaired.slides[0].source_pages == [253]
    assert len(repairs) == 1
    assert not ClaimValidator().validate_plan(repaired, observations, [chart])
    assert not repair_presentation_plan(repaired, observations, [chart])[1]
    assert observations[0].evidence[0].page == 238  # raw provenance is preserved


def test_mismatched_value_keeps_cross_context_claim_blocked() -> None:
    plan, chart = _plan_and_chart()
    observations = [
        *[_fact(f"other_{year}", year, value, context="FINANCIAL INFORMATION", page=238)
          for year, value in [(2023, 120578), (2024, 139487), (2025, 244691)]],
        *[_fact(f"chart_{year}", year, value, context="CURRENT ASSETS/LIABILITIES", page=253)
          for year, value in [(2023, 120578), (2024, 139486), (2025, 244691)]],
    ]

    repaired, repairs = repair_presentation_plan(plan, observations, [chart])

    assert repairs == []
    assert repaired.slides[0].observation_ids == ["other_2023", "other_2024", "other_2025"]
    assert any(issue.code == "directional_contradiction" for issue in ClaimValidator().validate_plan(repaired, observations, [chart]))


def test_single_period_overlap_does_not_establish_series_identity() -> None:
    plan, chart = _plan_and_chart()
    plan.slides[0].observation_ids = ["other_2023"]
    observations = [
        _fact("other_2023", 2023, 120578, context="FINANCIAL INFORMATION", page=238),
        *[_fact(f"chart_{year}", year, value, context="CURRENT ASSETS/LIABILITIES", page=253)
          for year, value in [(2023, 120578), (2024, 139486), (2025, 244691)]],
    ]

    repaired, repairs = repair_presentation_plan(plan, observations, [chart])

    assert repairs == []
    assert repaired.slides[0].observation_ids == ["other_2023"]


def test_unplotted_secondary_metric_uses_exact_superset_series() -> None:
    observations = [
        *[_fact(f"short_{year}", year, value, context="DISCUSSION", page=328)
          for year, value in [(2021, 345007), (2022, 375338), (2023, 341055)]],
        *[_fact(f"full_{year}", year, value, context="CURRENT ASSETS", page=342)
          for year, value in [(2021, 345007), (2022, 375338), (2023, 341055), (2024, 293546)]],
    ]
    slide = PresentationSlide(
        id="liquidity", slide_type="analysis",
        title="Inventories decreased from 2021-12-31 to 2024-12-31",
        observation_ids=["short_2021", "short_2022", "short_2023", "full_2021", "full_2022", "full_2023", "full_2024"],
        visual_blocks=[PresentationVisualBlock(
            role="kpi", observation_ids=["short_2021", "short_2023", "full_2024"],
        )],
        source_pages=[328, 342],
    )
    plan = PresentationPlan(title="Liquidity", slides=[slide])

    assert any(issue.code == "directional_contradiction" for issue in ClaimValidator().validate_plan(plan, observations))
    repaired, repairs = repair_presentation_plan(plan, observations)

    assert len(repairs) == 1
    assert repaired.slides[0].observation_ids == [f"full_{year}" for year in (2021, 2022, 2023, 2024)]
    assert repaired.slides[0].visual_blocks[0].observation_ids == ["full_2021", "full_2023", "full_2024"]
    assert repaired.slides[0].source_pages == [342]
    assert not ClaimValidator().validate_plan(repaired, observations)
    assert observations[0].evidence[0].page == 328


def test_unplotted_conflicting_source_is_not_silently_aligned() -> None:
    observations = [
        *[_fact(f"short_{year}", year, value, context="DISCUSSION", page=328)
          for year, value in [(2021, 345007), (2022, 375339), (2023, 341055)]],
        *[_fact(f"full_{year}", year, value, context="CURRENT ASSETS", page=342)
          for year, value in [(2021, 345007), (2022, 375338), (2023, 341055), (2024, 293546)]],
    ]
    plan = PresentationPlan(title="Liquidity", slides=[PresentationSlide(
        id="liquidity", slide_type="analysis",
        title="Inventories decreased from 2021-12-31 to 2024-12-31",
        observation_ids=[item.id for item in observations], source_pages=[328, 342],
    )])

    repaired, repairs = repair_presentation_plan(plan, observations)

    assert repairs == []
    assert repaired.slides[0].observation_ids == [item.id for item in observations]
    assert any(issue.code == "directional_contradiction" for issue in ClaimValidator().validate_plan(repaired, observations))
