import pytest

from adaptive_document_agent.services.source_day_count import (
    literal_day_count_conventions, mask_day_count_conventions,
)
from adaptive_document_agent.agent.retained_page_sources import RetainedPage, page_bindings
from adaptive_document_agent.agent import retained_analysis as retained
from tests.test_retained_analysis_v216 import _linked_result

DEFINITION = ('The ratio is calculated by dividing the average balance by revenue, then multiplying '
              'by the number of days in that period (i.e., 360 days for a given year and '
              '180 days for a six-month period).')
COPY = 'The source uses 360 days for a given year and 180 days for a six-month period in this calculation.'


def test_literal_parameters_preserve_values_and_do_not_expand_measurements():
    phrases = literal_day_count_conventions(DEFINITION)
    assert phrases == {'360 days for a given year', '180 days for a six-month period'}
    assert '360' not in mask_day_count_conventions(COPY, phrases)
    assert '180' not in mask_day_count_conventions(COPY, phrases)
    assert not literal_day_count_conventions('The measured turnover was 360 days for a given year.')
    assert not literal_day_count_conventions('The calculated balance was RMB360 thousand.')
    assert mask_day_count_conventions('The balance was 360.', phrases) == 'The balance was 360.'


@pytest.mark.parametrize('mutation', [None, 'missing_quote', 'changed_value', 'unrelated_amount', 'not_method'])
def test_page_accepts_only_exact_quoted_method_parameters(mutation):
    result = _linked_result()
    result.document.pages[0].text += '\n' + DEFINITION
    context = retained.selection_context(result, source_authoring=True)
    insight, primary, _ = next(iter(retained.findings(result, allow_new_copy=True).values()))
    text = COPY
    if mutation == 'changed_value':
        text = text.replace('360', '365')
    elif mutation == 'unrelated_amount':
        text += ' The balance was RMB360 thousand.'
    elif mutation == 'not_method':
        text = 'The observed balance was 360.'
    page = RetainedPage(title='Revenue', message=text,
        context_evidence=[] if mutation == 'missing_quote' else [dict(page=234, text=DEFINITION)])
    if mutation:
        with pytest.raises(ValueError, match='outside its bound evidence'):
            page_bindings(page, insight, primary, context, result)
    else:
        assert page_bindings(page, insight, primary, context, result)[2] == primary


def test_compiled_plan_rechecks_definition_parameters_without_licensing_another_value():
    from copy import deepcopy
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    from tests.test_retained_analysis_v216 import gateway
    result = _linked_result()
    result.document.pages[0].text += '\n' + DEFINITION
    result.document.pages[0].text_blocks = [dict(lines=[dict(text='Source table')])]
    original = deepcopy(result.observations)
    iid = result.insights[0].id
    response = dict(decisions=[dict(insight_id=iid, decision='include', reason='Source method.',
        page=dict(title='Revenue', message=COPY, companion_ids=[],
                  context_evidence=[dict(page=234, text=DEFINITION)]))], ordered_insight_ids=[iid])
    retained.select_retained_analysis(gateway([response, dict(accepted=True,
        reason='Synthetic independent source review.')]), result)
    result.presentation_plan = retained.compile_retained_analysis(result)
    PresentationPlanValidator().validate(result.presentation_plan, result)
    assert result.observations == original
    slide = next(s for s in result.presentation_plan.slides if s.slide_type == 'analysis')
    slide.message = slide.message.replace('360', '365')
    with pytest.raises(ValueError, match='unsupported numeric claims'):
        PresentationPlanValidator().validate(result.presentation_plan, result)
