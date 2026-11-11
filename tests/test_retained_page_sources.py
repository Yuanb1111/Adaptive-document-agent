import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_analysis_review import review_complete
from tests.test_retained_analysis_v216 import _linked_result, gateway


@pytest.mark.parametrize('mutation', ['valid', 'invented_quote', 'unsupplied_page', 'extra_number'])
def test_related_qualitative_evidence_adds_provenance_but_never_numeric_eligibility(mutation):
    from adaptive_document_agent.models import DocumentPage
    from adaptive_document_agent.agent.retained_page_sources import (
        RetainedPage, page_bindings, planned_source_citations,
    )
    result = _linked_result()
    source = 'A fulfillment constraint applies. The separately defined amount is RMB 987654321 thousand.'
    result.document.pages.append(DocumentPage(page_number=235, text=source))
    context = retained.selection_context(result, source_authoring=True)
    if mutation != 'unsupplied_page':
        context['source_pages'].append(dict(page=235, text=source))
    insight, primary, _ = next(iter(retained.findings(result, allow_new_copy=True).values()))
    page = RetainedPage(title='Revenue', message='The source describes a fulfillment constraint.',
        context_evidence=[dict(page=235, text=source if mutation != 'invented_quote' else 'No constraint applies.')])
    if mutation == 'extra_number':
        page.message += ' The amount is RMB 987654321 thousand.'
    if mutation != 'valid':
        with pytest.raises(ValueError, match='Context evidence|outside its bound evidence'):
            page_bindings(page, insight, primary, context, result)
        return
    _, _, ids = page_bindings(page, insight, primary, context, result)
    assert ids == primary
    selection = retained.RetainedAnalysisSelection(decisions=[dict(insight_id=insight.id,
        decision='include', reason='Qualitative context matters.', page=page)], ordered_insight_ids=[insight.id])
    citation, = planned_source_citations(selection, context, result)
    assert citation['source_pages'] == [234, 235]
    assert set(citation['observation_ids']) == primary
    assert result.document.pages[-1].text == source


@pytest.mark.parametrize('text,accepted', [
    ('The calculated CAGR was 10.0% from FY2021 to FY2023.', True),
    ('The calculated CAGR was 10.0% from FY2022 to FY2023.', False),
    ('The calculated CAGR was 10.0% from 2021 to 2023.', False),
    ('The calculated CAGR was 21.0% from FY2021 to FY2023.', False),
    ('The calculated CAGR was 10.0%.', False),
    ('The reported calculated CAGR was 10.0% from FY2021 to FY2023.', False),
    ('The margin was 10.0% from FY2021 to FY2023.', False),
])
def test_calculated_cagr_level_binds_its_exact_fiscal_interval(text, accepted):
    from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support
    result = _linked_result()
    observations = [o.model_copy(update=dict(period=period, value=value, raw_value=str(value)))
                    for o, period, value in zip(result.observations,
                        ['FY2021', 'FY2022', 'FY2023'], [100.0, 110.0, 121.0])]
    assert _numeric_support(text, observations) is accepted


def test_unbound_percentage_repair_feedback_identifies_the_offending_claim():
    from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support
    diagnostics = []
    assert not _numeric_support('Management states an aging proportion below 3%.',
                                _linked_result().observations, diagnostics=diagnostics)
    assert any('Unbound percentage claim: 3%' in message for message in diagnostics)


@pytest.mark.parametrize('mutation', [None, 'missing_quote', 'wrong_date', 'extra_amount'])
def test_literal_context_date_supports_an_event_without_licensing_prose_amounts(mutation):
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage, page_bindings
    result = _linked_result()
    source = 'As of October 31, 2028, most balances had been settled. The amount was RMB987654321 thousand.'
    result.document.pages[0].text += '\n' + source
    context = retained.selection_context(result, source_authoring=True)
    insight, primary, _ = next(iter(retained.findings(result, allow_new_copy=True).values()))
    date = '2028-10-30' if mutation == 'wrong_date' else '2028-10-31'
    page = RetainedPage(title='Revenue', message=f'The source reports subsequent settlement as of {date}.',
        context_evidence=[] if mutation == 'missing_quote' else [dict(page=234, text=source)])
    if mutation == 'extra_amount':
        page.message += ' The amount was RMB987654321 thousand.'
    if mutation:
        with pytest.raises(ValueError, match='outside its bound evidence'):
            page_bindings(page, insight, primary, context, result)
    else:
        assert page_bindings(page, insight, primary, context, result)[2] == primary


@pytest.mark.parametrize('extra_amount', [False, True])
def test_quoted_qualitative_effect_does_not_require_a_new_numeric_comparison(extra_amount):
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage, page_bindings
    result = _linked_result()
    source = ('The company says material stocking lengthened the collection cycle. '
              'The related amount was RMB987654321 thousand.')
    result.document.pages[0].text += '\n' + source
    context = retained.selection_context(result, source_authoring=True)
    insight, primary, _ = next(iter(retained.findings(result, allow_new_copy=True).values()))
    page = RetainedPage(title='Revenue',
        message='The company attributes a longer collection cycle to material stocking.',
        context_evidence=[dict(page=234, text=source)])
    if extra_amount:
        page.message += ' The related amount was RMB987654321 thousand.'
        with pytest.raises(ValueError, match='outside its bound evidence'):
            page_bindings(page, insight, primary, context, result)
    else:
        assert page_bindings(page, insight, primary, context, result)[2] == primary


def test_positioned_source_can_restore_a_finding_without_publishing_its_rejected_copy():
    result = _linked_result()
    page = result.document.pages[0]
    page.text += ' Latest column (unaudited).'
    page.text_blocks = [dict(lines=[dict(text='(unaudited)', bbox=[90, 10, 100, 20]),
                                    dict(text='Source table heading', bbox=[0, 0, 100, 10])])]
    insight = result.insights[0]
    insight.narrative = insight.movement = 'Revenue was USD999.9 billion.'
    assert insight.id not in retained.findings(result)
    context = retained.selection_context(result, source_authoring=True)
    assert context['source_pages'][0]['layout_lines'][0][0] == '(unaudited)'
    assert context['findings'][0]['validated_copy'] is None
    draft = dict(title='Revenue', message='The latest revenue balance is unaudited.')
    def response(companions):
        decision = dict(insight_id=insight.id, decision='include', reason='Distinct supported finding.',
                        page=dict(**draft, companion_ids=companions))
        return dict(decisions=[decision], ordered_insight_ids=[insight.id])
    with pytest.raises(ValueError, match='companion rows'):
        retained.select_retained_analysis(gateway([response(['other-table']), dict(accepted=True,
            missing_insight_ids=[], reason='Synthetic coverage acceptance.')] * 2), result)
    retained.select_retained_analysis(gateway([response([]), dict(accepted=True,
        missing_insight_ids=[], reason='Synthetic independent coverage acceptance.')]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    slide, = (s for s in result.presentation_plan.slides if s.slide_type == 'analysis')
    assert slide.message == draft['message'] and slide.source_pages == [234]
    assert insight.narrative == 'Revenue was USD999.9 billion.'
    assert not review_complete(result)


@pytest.mark.parametrize('amount', ['RMB -119,245 thousand', '(RMB119,245) thousand',
                                   '(RMB119,245 thousand)'])
def test_source_authored_negative_cash_flow_reaches_export_plan_without_changing_raw_cells(amount):
    from tests.test_retained_display_evidence_v218 import _display_result
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

    result = _display_result('An obsolete description.')
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='RMB thousands')])]
    insight = result.insights[0]
    original = result.model_dump(include={'observations', 'insights', 'analysis_results'})
    page = dict(title='Operating Cash Flow', companion_ids=[],
                message=f'Operating cash flow was {amount} in FY2023, '
                        'RMB 437,002 thousand in FY2024 and RMB 445,134 thousand in FY2025.')
    response = dict(decisions=[dict(insight_id=insight.id, decision='include',
                    reason='Distinct cash-flow trajectory.', page=page)], ordered_insight_ids=[insight.id])
    retained.select_retained_analysis(gateway([response, dict(accepted=True,
        missing_insight_ids=[], reason='Synthetic coverage acceptance.')]), result)
    plan = retained.compile_retained_analysis(result)
    assert result.model_dump(include=set(original)) == original
    assert result.observations[0].raw_value == '(119,245)'
    slide, = (s for s in plan.slides if s.slide_type == 'analysis')
    slide.message += ' The additional balance was RMB -888,888 thousand.'
    with pytest.raises(ValueError, match='unsupported numeric claims'):
        PresentationPlanValidator().validate(plan, result)


@pytest.mark.parametrize('value', [119245000, None])
def test_parenthesized_raw_cell_cannot_license_negative_claim_without_typed_sign(value):
    from adaptive_document_agent.validation.presentation_numeric_evidence import observation_numeric_fields
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    result = _linked_result()
    item = result.observations[0].model_copy(update={'raw_value': '(119,245)', 'value': value})
    tokens = set().union(*(PresentationPlanValidator._numbers(v) for v in observation_numeric_fields(item)))
    assert '-119245' not in tokens


def test_extended_source_copy_is_preserved_for_later_review_and_physical_layout_checks():
    result = _linked_result()
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Source table')])]
    insight = result.insights[0]
    # Synthetic long copy exercises evidence retention, not a real editorial verdict.
    copy = ('Revenue was RMB267,025 thousand in FY2023, RMB325,257 thousand in FY2024 '
            'and RMB521,747 thousand in FY2025. ') * 10
    assert 900 < len(copy) < 2000
    response = dict(decisions=[dict(insight_id=insight.id, decision='include',
        reason='Synthetic source retention.', page=dict(title='Revenue', message=copy, companion_ids=[]))],
        ordered_insight_ids=[insight.id])
    mock = gateway([response, dict(accepted=True, missing_insight_ids=[], reason='Synthetic coverage only.')])
    retained.select_retained_analysis(mock, result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    slide, = (s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    assert slide.message == copy and slide.bullets == [copy]
    assert len(mock.client.calls) == 2 and not review_complete(result)


def test_chartless_retained_page_renders_complete_copy_and_all_source_rows():
    from pptx import Presentation
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.services.slide_compositor import render_composed_slide
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    result = _linked_result()
    result.charts = []
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Source table')])]
    iid = result.insights[0].id
    copy = ('Revenue was RMB267,025 thousand in FY2023, RMB325,257 thousand in FY2024 '
            'and RMB521,747 thousand in FY2025. The source describes revenue for each '
            'reported period. This final qualification must remain visible in full.')
    response = dict(decisions=[dict(insight_id=iid,decision='include',reason='Trend',
        page=dict(title='Revenue',message=copy,companion_ids=[]))],ordered_insight_ids=[iid])
    retained.select_retained_analysis(gateway([response,dict(accepted=True,missing_insight_ids=[],
        reason='Synthetic review')]),result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    slide, = (s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    assert slide.visual_blocks and not slide.chart_ids
    assert set(slide.observation_ids) == {oid for b in slide.visual_blocks for oid in b.observation_ids}
    pages = render_composed_slide(Presentation(str(_resolve_template_path())),slide,[],result,DocumentIndex(result.observations))
    text = ' '.join(shape.text for page in pages for shape in page.shapes if shape.has_text_frame)
    for sentence in copy.split('. '):
        assert ' '.join(sentence.split()) in ' '.join(text.split())
    visible_ids = {oid for page in pages for shape in page.shapes
                   if shape.name.startswith(('table:', 'kpi:'))
                   for oid in shape.name.split(':', 1)[1].split(',')}
    assert set(slide.observation_ids) <= visible_ids


def test_source_interpretation_does_not_inherit_the_simple_selection_reasoning_reduction():
    from adaptive_document_agent.services.llm import LLMSettings
    from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
    settings = LLMSettings(simple_task_reasoning='reduced')
    policy = request_reasoning_policy(settings, stage='presentation',
        operation=retained.SourceAuthoredAnalysisSelection.__name__, model=settings.model)
    assert policy['intent'] == 'preserve' and policy['options'] == {}
    legacy = request_reasoning_policy(settings, stage='presentation',
        operation=retained.RetainedAnalysisSelection.__name__, model=settings.model)
    assert legacy['intent'] == 'reduce'


def test_source_authored_chart_retains_dated_middle_values_and_qualifications():
    from pptx import Presentation
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.services.slide_compositor import render_composed_slide
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    from adaptive_document_agent.services.presentation_trajectory import supported_subtitle
    from adaptive_document_agent.services.retained_display_copy import is_source_authored_message
    result = _linked_result()
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Source table')])]
    last = next(o for o in result.observations if o.period == 'FY2025')
    last.value, last.raw_value = 200000000, '200,000'
    iid = result.insights[0].id
    copy = ('Revenue was RMB267,025 thousand in FY2023, RMB325,257 thousand in FY2024 '
            'and RMB200,000 thousand in FY2025. Revenue increased from FY2023 to FY2024. '
            'The final source qualification must stay visible.')
    response = dict(decisions=[dict(insight_id=iid, decision='include', reason='Trend',
        page=dict(title='Revenue',message=copy,companion_ids=[]))],ordered_insight_ids=[iid])
    retained.select_retained_analysis(gateway([response,dict(accepted=True,missing_insight_ids=[],
        reason='Synthetic coverage')]),result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    slide, = (s for s in result.presentation_plan.slides if s.slide_type == 'analysis')
    charts = [c for c in result.charts if c.id in slide.chart_ids]
    index = DocumentIndex(result.observations)
    assert charts and supported_subtitle(slide,charts,index) != copy
    pages = render_composed_slide(Presentation(str(_resolve_template_path())),slide,charts,result,index)
    text = ' '.join(shape.text for page in pages for shape in page.shapes if shape.has_text_frame)
    for sentence in copy.split('. '):
        assert ' '.join(sentence.split()) in ' '.join(text.split())
    assert is_source_authored_message(result,slide)
    assert is_source_authored_message(result,slide.model_copy(update={'message':copy.split('. ')[0]+'.'}))
    assert not is_source_authored_message(result,slide.model_copy(update={'message':copy[:40]}))
    assert not is_source_authored_message(result,slide.model_copy(update={'message':'Changed copy'}))
    assert not review_complete(result)
