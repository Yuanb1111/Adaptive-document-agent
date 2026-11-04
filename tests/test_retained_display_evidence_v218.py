"""The selector and analytical pages must ground display amounts in the same finding."""
import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent import retained_analysis_review as review
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_retained_analysis_v216 import _linked_result, gateway, selection, verdict


def test_retained_selection_citation_does_not_license_an_amount_with_the_same_digits():
    result = _linked_result()
    response = selection(result)
    rationale = 'The reported annual figures on page 234 provide a comparable basis.'
    response['decisions'][0]['reason'] = rationale
    retained.select_retained_analysis(gateway([response]), result)
    plan = retained.compile_retained_analysis(result)
    slide = next(s for s in plan.slides if s.slide_type == 'analysis')
    assert slide.selection_reason == rationale and slide.source_pages == [234]
    slide.selection_reason += ' The reported total was 234.'
    with pytest.raises(ValueError, match=r'unsupported numeric claims.*234'):
        PresentationPlanValidator().validate(plan, result)
    slide.selection_reason = 'The reported total is supported on page 2023.'
    with pytest.raises(ValueError, match='page outside its retained slide references'):
        PresentationPlanValidator().validate(plan, result)


def test_citations_need_every_page_in_a_range_and_preserve_other_numeric_spans():
    from adaptive_document_agent.validation.presentation_numeric_evidence import check_selection_page_references
    reason, errors = check_selection_page_references('See pp. 12–14, 17. The change was 17%.', {12, 13, 14, 17})
    assert not errors and '17%' in reason
    assert check_selection_page_references('See pp. 12–14, 17.', {12, 14, 17})[1]
    assert check_selection_page_references('See pages 14-12.', {12, 13, 14})[1]
    for text in ('On page 12, 17 people enrolled.', 'On pages 12, 17 people enrolled.'):
        masked, errors = check_selection_page_references(text, {12, 17})
        assert not errors and '17 people' in masked
    assert check_selection_page_references('See page 1,234.', {1, 234})[1]


@pytest.mark.parametrize('citation', [
    'pages 12 and 99', 'pages 12, 99 and 14', 'pp. 12, 99, and 14',
    'pages 12–14 AND 99', 'pp. 12, 14, and 1,099',
])
def test_closed_conjoined_citations_validate_every_page_without_licensing_later_values(citation):
    from adaptive_document_agent.validation.presentation_numeric_evidence import check_selection_page_references
    source = f'See {citation}. The result was 99.'
    mask, errors = check_selection_page_references(source, {12, 13, 14, 99, 1099})
    assert mask == 'See  . The result was 99.' and not errors
    assert check_selection_page_references(source, {12, 13, 14})[1]


def test_ambiguous_trailing_amounts_are_not_consumed_as_citations():
    from adaptive_document_agent.validation.presentation_numeric_evidence import check_selection_page_references
    for text in ('On pages 12 and 17 people enrolled.', 'On pages 12, 14, and 17 people enrolled.'):
        masked, errors = check_selection_page_references(text, {12})
        assert not errors and '17 people enrolled.' in masked
    masked, errors = check_selection_page_references('On pages 12 and 14, 17 people enrolled.', {12, 14})
    assert not errors and masked == 'On  , 17 people enrolled.'


def _confidence_plan(score_text):
    from adaptive_document_agent.models.table import ExtractedTable
    result = _linked_result()
    page = result.document.pages[0]
    table = ExtractedTable(table_id='source-table', page=page.page_number, confidence=.73)
    page.tables = [table]
    for obs in result.observations:
        obs.table_id = table.table_id
        obs.evidence = [obs.evidence[0].model_copy(update={'page': page.page_number, 'table_id': table.table_id})]
    response = selection(result)
    reason = 'Relevant annual change; the reported table extraction confidence is ' + score_text + '.'
    response['decisions'][0]['reason'] = reason
    retained.select_retained_analysis(gateway([response]), result)
    plan = retained.compile_retained_analysis(result)
    slide = next(s for s in plan.slides if s.slide_type == 'analysis')
    assert slide.selection_reason == reason
    return result, plan, slide


@pytest.mark.parametrize('score_text', ['0.73', '73%'])
def test_retained_reason_can_cite_its_source_table_confidence(score_text):
    result, plan, slide = _confidence_plan(score_text)
    slide.message += ' The reported margin was 0.73.'
    with pytest.raises(ValueError, match=r'unsupported numeric claims.*0\.73'):
        PresentationPlanValidator().validate(plan, result)


@pytest.mark.parametrize('change', ['score', 'missing_score', 'table', 'page', 'missing_evidence', 'mixed', 'collision'])
def test_confidence_requires_exact_owners_even_if_a_financial_number_matches(change):
    result, plan, slide = _confidence_plan('0.73')
    page = result.document.pages[0]
    table = page.tables[0]
    if change == 'score':
        table.confidence = .72
    elif change == 'missing_score':
        page.tables = [type(table).model_validate(table.model_dump(exclude={'confidence'}))]
        slide.selection_reason = 'Table extraction confidence is 0.5.'
    elif change == 'table':
        table.table_id = 'unrelated'
    elif change == 'page':
        table.page += 1
    elif change == 'missing_evidence':
        result.observations[0].evidence = []
    elif change == 'mixed':
        page.tables.append(table.model_copy(update={'table_id': 'different', 'confidence': .75}))
        result.observations[0].table_id = 'different'
        result.observations[0].evidence[0].table_id = 'different'
    else:
        slide.selection_reason = f'Table extraction confidence is {result.observations[0].raw_value}.'
    with pytest.raises(ValueError, match='no matching extraction confidence'):
        PresentationPlanValidator().validate(plan, result)


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
