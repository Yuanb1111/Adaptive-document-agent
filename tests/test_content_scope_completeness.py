"""Synthetic source-declared category scopes stay complete and qualified."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.models import (
    DocumentPage, DocumentProfile, Observation, ParsedDocument, PipelineResult,
    PresentationTopic, PresentationTopicSelection, SourceEvidence,
)
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.source_scope_completeness import reconcile_source_scopes


def source_result(*, complete_claim=True):
    names = ['Home territory', 'North markets', 'South markets', 'Island markets']
    rows = [[name, str(10 + i), str(20 + i)] for i, name in enumerate(names)]
    rows += [['Total', '46', '86']]
    table = ExtractedTable(table_id='source', page=4, headers=['Metric', 'FY2022', 'FY2023'],
        column_periods=[None, 'FY2022', 'FY2023'], column_types=['label', 'amount', 'amount'],
        rows=[TableRow(cells=row, page=4) for row in rows], confidence=.95)
    paragraph = (
        'Revenue comes from (1) Home territory, (2) North markets, (3) South markets, '
        'and (4) Island markets, which refer to islands other than Home territory. '
        'The following table sets forth a breakdown of our revenue by market for the years indicated.'
    )
    result = PipelineResult(document=ParsedDocument(document_id='sample', sha256='synthetic',
        safe_filename='sample.pdf', page_count=4,
        pages=[DocumentPage(page_number=4, text=paragraph, tables=[table])]),
        profile=DocumentProfile(document_type='Study', analysis_page_ranges=[(4, 4)]))
    for i, row in enumerate(rows):
        for j, period in enumerate(['FY2022', 'FY2023'], 1):
            label = row[0] if i in (0, 4) else 'Subtotal of ' + row[0]
            table.rows[i].cells[0] = label
            result.observations.append(Observation(id=f'row-{i}-{j}', metric_original=label,
                value=float(row[j]), raw_value=row[j], unit='currency', raw_unit='USD', currency='USD',
                period=period, period_type='fiscal_year', period_basis='FY', unit_scale=1,
                row_id=i, column_id=j, confidence=.95,
                evidence=[SourceEvidence(page=4, text=row[j], table_id='source',
                                         row_label=label, column_label='Amount', extraction_method='digital_table', confidence=.95)]))
    directory, _ = series_directory(result)
    selected = [entry['id'] for entry in directory if entry['metric'].startswith('Subtotal of')]
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id='markets', title='Revenue rose across all major markets' if complete_claim else 'Selected markets',
        question='How did the selected markets perform?', rationale='Source regional values are comparable.',
        takeaway='Revenue rose across all major markets' if complete_claim else 'Selected reported values.',
        series_ids=selected)])
    return result


def test_declared_scope_completes_only_exact_reconciled_source_family():
    result = source_result()
    original = deepcopy(result.observations)
    changed = reconcile_source_scopes(result)
    assert changed == {'markets'}
    _, lookup = series_directory(result)
    topic = result.presentation_topics.topics[0]
    assert len(topic.series_ids) == 4
    assert {lookup[s][0].metric_original for s in topic.series_ids} == {
        'Home territory', 'Subtotal of North markets', 'Subtotal of South markets', 'Subtotal of Island markets'}
    assert 'other than Home territory' in topic.question
    assert 'Home territory' in topic.question
    assert 'Revenue by market' == topic.title
    assert result.observations == original
    before = result.model_dump_json()
    assert reconcile_source_scopes(result) == set()
    assert result.model_dump_json() == before


@pytest.mark.parametrize('fault', ['missing', 'conflict', 'different_table', 'unbalanced', 'ambiguous_row'])
def test_incomplete_or_ambiguous_source_is_disclosed_not_guessed(fault):
    result = source_result()
    _, initial_lookup = series_directory(result)
    item = result.observations[0]
    if fault == 'missing':
        result.observations.remove(item)
    elif fault == 'conflict':
        result.observations.append(item.model_copy(update={'id': 'conflict', 'value': 99}))
    elif fault == 'different_table':
        item.evidence[0].table_id = 'elsewhere'
    elif fault == 'unbalanced':
        result.observations[-1].value = 999
    else:
        result.document.pages[0].tables[0].rows[0].alignment_status = 'ambiguous'
    original = deepcopy(result.observations)
    reconcile_source_scopes(result, initial_lookup if fault == 'ambiguous_row' else None)
    assert len(result.presentation_topics.topics[0].series_ids) == 3
    assert 'all major' not in result.presentation_topics.topics[0].title.lower()
    assert any(issue.code == 'presentation_source_scope_incomplete' for issue in result.validation_warnings)
    assert result.observations == original


def test_explicit_partial_selection_is_not_expanded_but_exclusion_qualifier_survives():
    result = source_result(complete_claim=False)
    reconcile_source_scopes(result)
    topic = result.presentation_topics.topics[0]
    assert len(topic.series_ids) == 3
    assert topic.title == 'Selected markets'
    assert 'other than Home territory' in topic.question


def test_unrelated_numbered_prose_cannot_expand_the_selected_scope():
    result = source_result()
    result.document.pages[0].text = 'Tasks: (1) Read, (2) Write, (3) Check, (4) Publish.'
    before = result.model_dump_json()
    assert not reconcile_source_scopes(result)
    assert result.model_dump_json() == before


def test_exact_source_total_cells_can_verify_a_family_without_total_observations():
    result = source_result()
    result.observations = result.observations[:-2]
    before = deepcopy(result.observations)
    assert reconcile_source_scopes(result) == {'markets'}
    assert len(result.presentation_topics.topics[0].series_ids) == 4
    assert result.observations == before


@pytest.mark.parametrize('fault', ['missing_total', 'ambiguous_total', 'wrong_total', 'missing_cell', 'changed_scale'])
def test_raw_total_reconciliation_never_fills_missing_or_incompatible_values(fault):
    result = source_result()
    result.observations = result.observations[:-2]
    table = result.document.pages[0].tables[0]
    if fault == 'missing_total':
        table.rows.pop()
    elif fault == 'ambiguous_total':
        table.rows[-1].alignment_status = 'ambiguous'
    elif fault == 'wrong_total':
        table.rows[-1].cells[-1] = '999'
    elif fault == 'missing_cell':
        table.rows[-1].cells.pop()
    else:
        result.observations[0].value *= 1000
    reconcile_source_scopes(result)
    assert len(result.presentation_topics.topics[0].series_ids) == 3


def test_series_directory_restores_exact_table_scope_for_repeated_labels():
    result = source_result()
    # A same-named measure from a different table must not make the verified
    # source partition unavailable, nor may that other value enter its total.
    repeated = [item.model_copy(deep=True) for item in result.observations[:2]]
    for item in repeated:
        item.id += '-different-context'
        item.value += 100
        item.evidence[0].table_id = 'other-source'
    result.observations.extend(repeated)
    before = deepcopy(result.observations)
    reconcile_source_scopes(result)
    _, lookup = series_directory(result)
    topic = result.presentation_topics.topics[0]
    assert len(topic.series_ids) == 4
    assert {o.effective_table_id for sid in topic.series_ids for o in lookup[sid]} == {'source'}
    assert result.observations == before


def test_cached_replay_is_transactional_and_preserves_other_slides(monkeypatch):
    from adaptive_document_agent.models import PresentationPlan, PresentationSlide, PresentationTheme, PresentationVisualBlock
    from adaptive_document_agent.services.source_scope_completeness import prepare_cached_source_scopes
    result = source_result()
    topic = result.presentation_topics.topics[0]
    _, lookup = series_directory(result)
    selected_ids = [o.id for sid in topic.series_ids for o in lookup[sid]]
    result.presentation_plan = PresentationPlan(title='Source findings',
        themes=[PresentationTheme(id=topic.id, title=topic.title, question=topic.question,
                                  rationale=topic.rationale, observation_ids=selected_ids, source_pages=[4])],
        slides=[PresentationSlide(id='context', slide_type='cover', title='Preserved context'),
                PresentationSlide(id='overview', slide_type='company_overview', title='Overview'),
                PresentationSlide(id='summary', slide_type='executive_summary', title='Summary'),
                PresentationSlide(id='analysis', slide_type='analysis', title=topic.title,
                    theme_id=topic.id, observation_ids=selected_ids, source_pages=[4],
                    visual_blocks=[PresentationVisualBlock(role='table', observation_ids=selected_ids)]),
                PresentationSlide(id='quality', slide_type='data_quality', title='Coverage'),
                PresentationSlide(id='appendix', slide_type='appendix', title='Source data')])
    before = deepcopy(result.observations)
    preserved = result.presentation_plan.slides[0].model_dump_json()

    def compiled(snapshot):
        topic = snapshot.presentation_topics.topics[0]
        _, lookup = series_directory(snapshot)
        ids = [o.id for sid in topic.series_ids for o in lookup[sid]]
        return PresentationPlan(title='Recompiled scoped copy',
            themes=[PresentationTheme(id=topic.id, title=topic.title, question=topic.question,
                rationale=topic.rationale, observation_ids=ids, source_pages=[4])],
            slides=[PresentationSlide(id='scoped-matrix', slide_type='analysis', title=topic.title,
                message=topic.question, theme_id=topic.id, source_pages=[4],
                section_id=topic.id, section_title=topic.title, analytical_question=topic.question,
                selection_reason=topic.rationale,
                visual_blocks=[PresentationVisualBlock(role='matrix', matrix_dimension='source_metric', observation_ids=ids)])])

    monkeypatch.setattr('adaptive_document_agent.agent.topic_plan_compiler.compile_topic_plan', compiled)
    assert prepare_cached_source_scopes(result)
    assert result.presentation_plan.slides[0].model_dump_json() == preserved
    assert len(result.presentation_plan.slides[3].visual_blocks[0].observation_ids) == 8
    assert result.observations == before
    snapshot = result.model_dump_json()
    assert not prepare_cached_source_scopes(result)
    assert result.model_dump_json() == snapshot


def test_failed_cached_recompile_keeps_original_selection_and_plan(monkeypatch):
    from adaptive_document_agent.models import PresentationPlan
    from adaptive_document_agent.services.source_scope_completeness import prepare_cached_source_scopes
    result = source_result()
    result.presentation_plan = PresentationPlan(title='Existing plan')
    original = result.model_copy(deep=True)
    def failed(_):
        raise ValueError('Unresolved source binding')
    monkeypatch.setattr('adaptive_document_agent.agent.topic_plan_compiler.compile_topic_plan', failed)
    assert not prepare_cached_source_scopes(result)
    assert result.presentation_plan == original.presentation_plan
    assert result.presentation_topics == original.presentation_topics
    assert result.observations == original.observations
    assert result.validation_warnings[-1].code == 'presentation_source_scope_replay_failed'


@pytest.mark.parametrize('title,takeaway', [
    ('Selected markets', 'All selected markets rose.'),
    ('A partial market view', 'Every chosen market grew.'),
    ('Measured categories', 'All observations increased.'),
    ('A market subset', 'The entire selected sample grew.'),
])
def test_quantifier_must_name_the_complete_partition_not_selected_points(title, takeaway):
    result = source_result(complete_claim=False)
    topic = result.presentation_topics.topics[0]
    topic.title, topic.takeaway = title, takeaway
    reconcile_source_scopes(result)
    assert len(topic.series_ids) == 3
    assert topic.title == title and topic.takeaway == takeaway


@pytest.mark.parametrize('copy', [
    'Revenue rose in all markets except Home territory',
    'Revenue rose in all markets excluding Home territory',
    'Revenue rose in all markets other than Home territory',
    'Revenue rose in all but Home territory',
    'Revenue rose in not all markets',
])
def test_exhaustive_quantifier_with_explicit_exception_remains_partial(copy):
    result = source_result(complete_claim=False)
    topic = result.presentation_topics.topics[0]
    topic.title = topic.takeaway = copy
    reconcile_source_scopes(result)
    assert len(topic.series_ids) == 3
    assert topic.title == topic.takeaway == copy
