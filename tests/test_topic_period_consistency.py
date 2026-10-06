"""Selected comparison periods bind to each source series, not a pooled year bag."""
from copy import deepcopy
import json
import re

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.models import (
    ChartPlan, DocumentProfile, Observation, ParsedDocument, PipelineResult,
    PresentationTopic, PresentationTopicSelection, PresentationPlan,
    SourceEvidence,
)


def sample(*, alternatives=True):
    result = PipelineResult(document=ParsedDocument(document_id='synthetic', sha256='synthetic',
        safe_filename='study.pdf', page_count=20), profile=DocumentProfile(document_type='Study',
        analysis_page_ranges=[(1, 20)]))
    for number, name in enumerate(('North zone', 'South zone', 'East zone', 'West zone')):
        periods = ['FY2022', 'FY2023', 'FY2024']
        if number in (1, 3):
            periods = (periods if alternatives else []) + ['6M2023', '6M2024']
        for index, period in enumerate(periods):
            basis = '6M' if period.startswith('6M') else 'FY'
            result.observations.append(Observation(id=f'{number}-{period}', metric_original=name,
                value=10+number+index, raw_value=str(10+number+index), entity=name, unit='count', unit_family='count',
                period=period, period_type='interim_flow' if basis=='6M' else 'fiscal_year',
                period_basis=basis, confidence=.95, table_id='source', row_id=number,
                dimensions={'period_basis':basis, 'table_context':'Reported orders'},
                evidence=[SourceEvidence(page=4, table_id='source', row_label=name,
                    text=str(10+number+index), extraction_method='digital_table', confidence=.95)]))
    directory, lookup = series_directory(result)
    selected = []
    for number, name in enumerate(('North zone', 'South zone', 'East zone', 'West zone')):
        basis = '6M' if number in (1,3) else 'FY'
        selected.append(next(x['id'] for x in directory if x['metric']==name
                             and all(p.startswith(basis) for p in x['periods'])))
    for entry in directory:
        ids=[o.id for o in lookup[entry['id']]]
        result.charts.append(ChartPlan(id='chart-'+entry['id'], title=entry['metric'],
            question='How do reported values compare?', chart_type='bar', observation_ids=ids, source_pages=[4]))
    result.presentation_topics=PresentationTopicSelection(topics=[PresentationTopic(id='zones',
        title='Reported orders across zones',
        question='How did North zone, South zone, East zone and West zone change from FY2022 to FY2024?',
        rationale='The same source reports the selected operating measures.',
        series_ids=selected)])
    return result


def test_one_series_cannot_lend_its_years_to_another_selected_series():
    result=sample(); _,lookup=series_directory(result)
    with pytest.raises(ValueError, match='period'):
        PresentationTopicSelector._validate(result.presentation_topics,lookup)


def test_unique_same_source_period_rebinding_retains_all_topics_and_audits_raw_selection():
    result=sample(); original=deepcopy(result.observations); chosen=deepcopy(result.presentation_topics)
    plan=compile_topic_plan(result)
    _,lookup=series_directory(result)
    assert len(plan.themes)==1
    assert all({o.period for o in lookup[sid]}=={'FY2022','FY2023','FY2024'}
               for sid in result.presentation_topics.topics[0].series_ids)
    assert result.observations==original
    audit=json.loads(next(w.message for w in result.validation_warnings if w.code=='presentation_topic_period_rebound'))
    assert audit['original_topic']==chosen.topics[0].model_dump(mode='json')
    before=result.model_dump_json()
    compile_topic_plan(result)
    assert result.model_dump_json()==before


@pytest.mark.parametrize('difference',['table','row','metric','entity','unit','scale','currency','category','ifrs','invalid','ambiguous'])
def test_rebinding_never_guesses_another_source_scope(difference):
    result=sample(); _,lookup=series_directory(result)
    alternative=[o for o in result.observations if o.metric_original=='West zone' and o.period.startswith('FY')]
    for item in alternative:
        if difference=='table':item.table_id='different-source';item.evidence[0].table_id='different-source'
        elif difference=='row':item.evidence[0].row_label='Different source row'
        elif difference=='metric':item.metric_original='Different metric'
        elif difference=='entity':item.entity='Other group'
        elif difference=='unit':item.raw_unit='different unit'
        elif difference=='scale':item.unit_scale=1000
        elif difference=='currency':item.currency='USD'
        elif difference=='category':item.category_dimensions={'population':'Different'}
        elif difference=='ifrs':item.ifrs_status='ADJUSTED'
        elif difference=='invalid':item.validation_status='invalid'
        else:item.anomaly_notes=['Conflicting source']
    before=deepcopy(result.presentation_topics)
    with pytest.raises(ValueError):compile_topic_plan(result)
    assert result.presentation_topics==before  # No partial repairs on a failed topic


def test_period_rebinding_respects_explicit_omission():

    result=sample(); directory,_=series_directory(result)
    annual=next(x['id'] for x in directory if x['metric']=='West zone' and x['periods'][0]=='FY2022')
    result.presentation_topics = PresentationTopicSelection(topics=result.presentation_topics.topics, omissions=[{'series_id':annual,'reason':'This annual source is intentionally excluded.'}])
    with pytest.raises(ValueError):compile_topic_plan(result)


def test_separately_labeled_mixed_period_questions_remain_valid_and_pages_use_local_periods():
    result=sample()
    result.presentation_topics.topics[0].question=(
        'How did North zone and East zone change from FY2022 to FY2024? '
        'How did South zone and West zone change from 6M2023 to 6M2024?')
    _,lookup=series_directory(result)
    original=deepcopy(result.presentation_topics)
    PresentationTopicSelector._validate(result.presentation_topics,lookup)
    plan=compile_topic_plan(result)
    assert result.presentation_topics==original
    assert len(plan.themes)==1
    slides=[s for s in plan.slides if s.slide_type=='analysis']
    assert len(slides)==2
    # Balanced pagination is now 2+2: each page contains one FY series and
    # one 6M series. Test each page's actual evidence, not the former 3+1 tail.
    assert [len(slide.chart_ids) for slide in slides] == [2, 2]
    charts = {chart.id: chart for chart in result.charts}
    observations = {item.id: item for item in result.observations}
    from adaptive_document_agent.validation.topic_period_consistency import _period_matches
    for slide in slides:
        series = [[observations[oid] for oid in charts[cid].observation_ids]
                  for cid in slide.chart_ids]
        local = [item for group in series for item in group]
        for copy in (slide.title, slide.message, slide.analytical_question, slide.selection_reason):
            periods = re.findall(r'\b(?:FY|6M)\d{4}\b', copy)
            assert all(any(_period_matches(period, item) for item in local) for period in periods)
        # A period from another local panel still cannot authorize a wrong
        # range for this panel's explicitly named subject.
        for group in series:
            clauses = [clause for clause in slide.analytical_question.split('?')
                       if group[0].metric_original in clause]
            assert clauses
            assert all(any(_period_matches(period, item) for item in group)
                       for clause in clauses for period in re.findall(r'\b(?:FY|6M)\d{4}\b', clause))
    assert not any(w.code=='presentation_topic_period_rebound' for w in result.validation_warnings)


def test_cached_recovery_commits_rebound_topics_with_plan_atomically():
    result=sample();result.presentation_plan=PresentationPlan(title='Old fallback',planning_origin='fallback')
    assert PresentationPlanRecovery().recover_missing_plan(result)
    _,lookup=series_directory(result)
    assert all({o.period for o in lookup[sid]}=={'FY2022','FY2023','FY2024'}
               for sid in result.presentation_topics.topics[0].series_ids)
    before=result.model_dump_json()
    assert not PresentationPlanRecovery().recover_missing_plan(result)
    assert result.model_dump_json()==before


def test_a_range_for_one_panel_cannot_rebind_explicitly_separate_panels():
    result=sample()
    result.presentation_topics.topics[0].question=(
        'How did North zone change from FY2022 to FY2024, alongside the separately '
        'reported South zone, East zone and West zone measures?')
    from adaptive_document_agent.validation.topic_period_consistency import reconcile_topic_periods
    _, lookup=series_directory(result)
    before=result.presentation_topics.model_dump_json()
    PresentationTopicSelector._validate(result.presentation_topics, lookup)
    assert not reconcile_topic_periods(result, lookup)
    assert result.presentation_topics.model_dump_json()==before


def test_continuation_checks_full_period_labels_even_when_year_digits_match():
    from adaptive_document_agent.validation.topic_period_consistency import continuation_copy
    result=sample()
    items=[o for o in result.observations if o.metric_original=='West zone' and o.period.startswith('6M')]
    question, reason=continuation_copy('How did the measures change from FY2023 to FY2024?', '', items)
    assert 'FY' not in question+reason
    assert '6M2023' in reason and '6M2024' in reason


def test_continuation_reason_cannot_borrow_a_different_period_basis():
    from adaptive_document_agent.validation.topic_period_consistency import continuation_copy
    result=sample()
    items=[o for o in result.observations if o.metric_original=='West zone' and o.period.startswith('6M')]
    question,reason=continuation_copy('What was reported?', 'Compare FY2023 to FY2024 for each metric.',items)
    assert question=='What was reported?'
    assert not reason


def test_bare_year_alias_cannot_hide_conflicting_typed_period_evidence():
    from adaptive_document_agent.validation.topic_period_consistency import _period_matches
    item=sample().observations[0].model_copy(update={'period':'FY2023','period_basis':'6M','period_type':'interim_flow'})
    assert not _period_matches('2023',item)
    assert not _period_matches('FY2023',item)


@pytest.mark.parametrize('question', [
    'Explain the South zone, East zone and West zone interim results. How did North zone change from FY2022 to FY2024?',
    'How did North zone change from FY2022 to FY2024? What do the separately reported South zone, East zone and West zone measures show?',
    'What do the South zone, East zone and West zone measures show? How did North zone change from FY2022 to FY2024?',
])
def test_independent_question_sentences_never_share_one_range(question):
    from adaptive_document_agent.validation.topic_period_consistency import reconcile_topic_periods
    result=sample();result.presentation_topics.topics[0].question=question
    _,lookup=series_directory(result)
    before=result.presentation_topics.model_dump_json()
    PresentationTopicSelector._validate(result.presentation_topics,lookup)
    assert not reconcile_topic_periods(result,lookup)
    assert result.presentation_topics.model_dump_json()==before


def test_retained_source_definition_does_not_hide_shared_question_scope():
    result=sample()
    topic=result.presentation_topics.topics[0]
    definition='South zone: service locations other than the central district.'
    topic.question+=' '+definition;topic.caveats=[definition]
    plan=compile_topic_plan(result)
    assert len(plan.themes)==1
    assert topic.question.endswith(definition)
    assert any(w.code=='presentation_topic_period_rebound' for w in result.validation_warnings)


def test_literal_calendar_years_do_not_require_financial_semantics():
    from adaptive_document_agent.validation.topic_period_consistency import _period_matches
    item=sample().observations[0].model_copy(update={'period':'2023','period_basis':'','period_type':'generic'})
    assert _period_matches('2023',item)
    assert not _period_matches('FY2023',item)
    assert not _period_matches('2023',item.model_copy(update={'period_basis':'6M','period_type':'interim_flow'}))
