"""The selector and analytical pages must ground display amounts in the same finding."""
import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent import retained_analysis_review as review
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_retained_analysis_v216 import _linked_result, gateway, selection, verdict


def _display_result(movement):
    result = _linked_result()
    result.charts = []
    for item, (raw, value) in zip(result.observations, [
        ("(119,245)", -119_245_000), ("437,002", 437_002_000), ("445,134", 445_134_000)
    ]):
        item.raw_value, item.value = raw, value
        item.metric_original = "Operating cash flow"
        item.evidence = [item.evidence[0].model_copy(update={"text": f"{item.period}: {raw}"})]
    result.document.pages[0].text = "Operating cash flow, RMB thousands: FY2023 (119,245) FY2024 437,002 FY2025 445,134"
    task = result.analysis_plan[0]
    task.title = "Change in operating cash flow"
    task.analysis_type = task.tool_name = "absolute_change"
    calculation = result.analysis_results[0]
    calculation.title = task.title
    calculation.result = result.observations[-1].value - result.observations[0].value
    calculation.evidence = [item.evidence[0] for item in result.observations]
    finding = result.insights[0]
    finding.evidence = calculation.evidence
    finding.title = "Reported amounts"
    finding.narrative = "An unsupported draft amount of RMB999.9 million."
    finding.movement = movement
    return result


def test_signed_and_scaled_copy_reaches_independent_review_with_original_inputs():
    result = _display_result("RMB119.2 million used in operations in FY2023 and RMB437.0m in FY2024")
    original = result.model_dump(include={"observations", "analysis_results", "insights"})
    gw = gateway([selection(result)])
    retained.select_retained_analysis(gw, result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    [page] = [s for s in result.presentation_plan.slides if s.slide_type == "analysis"]
    assert page.insight_ids == retained.selected_record(result)["selection"]["ordered_insight_ids"]
    assert set(page.observation_ids) == {o.id for o in result.observations}
    assert page.bullet_observation_ids == [page.observation_ids]
    assert page.source_pages == [234]
    assert result.insights[0].movement in page.message
    review.review_retained_analysis(gateway([verdict(result)]), result)
    assert review.review_complete(result)
    assert result.model_dump(include=set(original)) == original

    # The very same coefficient elsewhere is still a separate claim.
    page.selection_reason = "The score was 437.0."
    with pytest.raises(ValueError, match=r"unsupported numeric claims.*437"):
        PresentationPlanValidator().validate(result.presentation_plan, result)


def test_rounded_derived_amount_keeps_its_python_calculation_reference():
    result = _display_result("An increase of RMB564.4 million from FY2023 to FY2025")
    gw = gateway([selection(result)])
    retained.select_retained_analysis(gw, result)
    plan = retained.compile_retained_analysis(result)
    [page] = [s for s in plan.slides if s.slide_type == "analysis"]
    from adaptive_document_agent.services.presentation_evidence import calculation_catalog
    catalog = calculation_catalog(result.observations)
    assert any(catalog[cid]["value"] == result.analysis_results[0].result for cid in page.calculation_ids)
    page.calculation_ids.clear()
    with pytest.raises(ValueError, match=r"unsupported numeric claims.*564.4"):
        PresentationPlanValidator().validate(plan, result)


@pytest.mark.parametrize("movement", [
    "Positive RMB119.2 million in FY2023",
    "Positive RMB119.2 million used in operations in FY2023",
    "Negative RMB437.0m in FY2024",
    "USD437.0m in FY2024",
    "RMB437.0 billion in FY2024",
    "RMB437.01 million in FY2024",
    "RMB0 billion in FY2023",
    "RMB437.0 million per employee in FY2024",
    "RMB123.4 million in FY2024",
])
def test_incompatible_display_cannot_be_selected(movement):
    result = _display_result(movement)
    # A compatible amount on the same source page is outside this finding's inputs.
    result.observations.append(result.observations[1].model_copy(update={
        "id": "unrelated", "value": 123_400_000, "raw_value": "123,400",
    }))
    assert result.insights[0].id not in retained.findings(result)
