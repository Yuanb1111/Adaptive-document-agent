"""Exact source reuse preserves complete series and current snapshot ownership."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent import presentation_topic_selector as selector
from adaptive_document_agent.models import (
    DocumentPage, DocumentProfile, ExtractedTable, Observation, ParsedDocument, PipelineResult,
    SourceEvidence, TableRow,
)
from adaptive_document_agent.utils.series_directory_cache import SeriesDirectoryCache


@pytest.fixture
def builds(monkeypatch):
    monkeypatch.setattr(selector, '_series_directory_cache', SeriesDirectoryCache())
    original, calls = selector._build_series_directory, []
    def build(result):
        calls.append(True)
        return original(result)
    monkeypatch.setattr(selector, '_build_series_directory', build)
    return calls


def source():
    table = ExtractedTable(table_id='reported', page=1,
        headers=['Measure', '2021', '2022', '2023'], bbox=(10, 20, 400, 120),
        raw_header_lines=['Year ended December 31,', '2021 2022 2023', '(USD in thousands)'],
        raw_body_lines=['Programme fees 10 5 20'], rows=[
            TableRow(cells=['Programme fees', '10', '5', '20'], page=1, alignment_status='resolved')])
    text = '\n'.join([*table.raw_header_lines, *table.raw_body_lines])
    return PipelineResult(document=ParsedDocument(document_id='series-source', sha256='fixed-source-label',
        safe_filename='source.pdf', page_count=1, pages=[DocumentPage(page_number=1, text=text,
            raw_text=text, tables=[table], raw_tables=[table.model_copy(deep=True)],
            text_blocks=[{'lines': [{'text': 'Programme fees 10 5 20', 'bbox': [10, 50, 400, 70]}]}])]),
        profile=DocumentProfile(), observations=[Observation(id=f'fees-{year}',
            metric_original='Programme fees', value=value, raw_value=str(value), unit='currency',
            raw_unit='USD in thousands', unit_scale=1000, currency='USD', period=f'FY{year}',
            period_type='fiscal_year', period_basis='FY', table_id='reported', row_id=0, column_id=index+1,
            confidence=1, evidence=[SourceEvidence(page=1, table_id='reported', row_label='Programme fees',
                column_label=str(year), text=f'Programme fees {value}',
                extraction_method='digital_table', confidence=1)])
            for index, (year, value) in enumerate([(2021, 10), (2022, 5), (2023, 20)])])


def test_equal_deepcopy_hits_cache_and_rebinds_every_original_and_interior_point(builds):
    result = source()
    original, original_lookup = selector.series_directory(result)
    current = deepcopy(result)
    before = current.model_dump_json()
    directory, lookup = selector.series_directory(current)
    assert len(builds) == 1 and directory == original
    assert list(lookup) == list(original_lookup)
    sid = directory[0]['id']
    assert [point[2] for point in directory[0]['reported_points']] == ['10', '5', '20']
    assert [item.id for item in lookup[sid]] == [item.id for item in original_lookup[sid]]
    current_ids = {item.id: item for item in current.observations}
    assert all(item is current_ids[item.id] for item in lookup[sid])
    assert all(item is not old for item, old in zip(lookup[sid], original_lookup[sid]))
    assert current.model_dump_json() == before


@pytest.mark.parametrize('mutation', [
    'document_id', 'document_sha', 'value', 'raw_value', 'unit', 'currency', 'period',
    'period_basis', 'evidence', 'source_text', 'raw_text', 'raw_table_geometry',
    'geometry', 'source_table_alignment',
])
def test_every_changed_source_or_value_dependency_invalidates_the_cache(builds, mutation):
    result = source()
    directory, _ = selector.series_directory(result)
    assert directory and len(builds) == 1
    if mutation == 'document_id': result.document.document_id = 'another-document'
    elif mutation == 'document_sha': result.document.sha256 = 'another-source'
    elif mutation == 'value': result.observations[1].value = 7
    elif mutation == 'raw_value': result.observations[1].raw_value = '5.0'
    elif mutation == 'unit': result.observations[1].unit = 'count'
    elif mutation == 'currency': result.observations[1].currency = 'EUR'
    elif mutation == 'period': result.observations[1].period = 'FY2024'
    elif mutation == 'period_basis': result.observations[1].period_basis = 'Different reported scope'
    elif mutation == 'evidence': result.observations[1].evidence[0].text = 'Different source evidence.'
    elif mutation == 'source_text': result.document.pages[0].text += '\nA source qualification.'
    elif mutation == 'raw_text': result.document.pages[0].raw_text += '\nA retained raw passage.'
    elif mutation == 'raw_table_geometry': result.document.pages[0].raw_tables[0].bbox = (10, 25, 400, 130)
    elif mutation == 'geometry': result.document.pages[0].text_blocks[0]['lines'][0]['bbox'][1] = 55
    else: result.document.pages[0].tables[0].rows[0].alignment_status = 'ambiguous'
    updated, lookup = selector.series_directory(result)
    assert len(builds) == 2
    if mutation == 'source_table_alignment': assert updated == [] and lookup == {}
    current_ids = {item.id: item for item in result.observations}
    assert all(item is current_ids[item.id] for group in lookup.values() for item in group)


def test_returned_nested_directory_and_lookup_lists_cannot_pollute_cached_data(builds):
    result = source()
    expected, _ = selector.series_directory(result)
    directory, lookup = selector.series_directory(result)
    directory[0]['reported_points'][1][2] = 'Caller-invented value'
    directory[0]['dimensions']['invented'] = 'Caller context'
    lookup[directory[0]['id']].clear()
    actual, current_lookup = selector.series_directory(result)
    assert actual == expected and len(next(iter(current_lookup.values()))) == 3
    assert len(builds) == 1


def test_mutating_rebound_lookup_changes_only_current_snapshot_and_forces_new_build(builds):
    original = source()
    selector.series_directory(original)
    current = deepcopy(original)
    _, lookup = selector.series_directory(current)
    next(iter(lookup.values()))[1].raw_value = '5.00'
    assert original.observations[1].raw_value == '5'
    directory, _ = selector.series_directory(current)
    assert directory[0]['reported_points'][1][2] == '5.00'
    assert len(builds) == 2


def ratio_source():
    result = source()
    table = result.document.pages[0].tables[0]
    table.raw_body_lines = ['Training ratio(1) 10 5 20']
    table.rows[0].cells[0] = 'Training ratio'
    result.document.pages[0].text = ('Training ratio(1) 10 5 20\n'
        '(1) Calculated by dividing staff training expenses by total programme expenditure '
        'and multiplied by 100%.')
    for item in result.observations:
        item.metric_original = 'Training ratio'
        item.unit, item.currency, item.raw_unit, item.unit_scale = 'percent', None, '%', 1
        item.evidence[0].row_label = 'Training ratio'
    return result


def test_ratio_definition_and_literal_row_qualification_changes_cannot_reuse_old_directory(builds):
    result = ratio_source()
    first, _ = selector.series_directory(result)
    assert first[0]['ratio_definitions'][0]['denominator'] == 'total programme expenditure'
    assert first[0]['source_qualifications']
    result.document.pages[0].text = result.document.pages[0].text.replace(
        'total programme expenditure', 'total operating expenditure')
    changed, _ = selector.series_directory(result)
    assert changed[0]['ratio_definitions'][0]['denominator'] == 'total operating expenditure'
    assert 'total operating expenditure' in changed[0]['source_qualifications'][0]['text']
    result.document.pages[0].tables[0].raw_body_lines = ['Training ratio 10 5 20']
    without_row_marker, _ = selector.series_directory(result)
    assert without_row_marker[0]['source_qualifications'] == []
    assert len(builds) == 3


def test_duplicate_observation_ids_preserve_original_records_without_caching(builds):
    result = source()
    result.observations[1].id = result.observations[0].id
    first, first_lookup = selector.series_directory(result)
    second, second_lookup = selector.series_directory(result)
    assert first == second and len(builds) == 2
    assert list(first_lookup.values())[0][0] is result.observations[0]
    assert list(second_lookup.values())[0][1] is result.observations[1]


def test_cache_has_at_most_four_entries_and_uses_lru_eviction(builds):
    results = [source() for _ in range(5)]
    for index, result in enumerate(results):
        result.document.document_id = str(index)
        selector.series_directory(result)
    assert len(selector._series_directory_cache._values) == 4 and len(builds) == 5
    selector.series_directory(deepcopy(results[1]))
    assert len(builds) == 5
    selector.series_directory(deepcopy(results[0]))
    assert len(builds) == 6 and len(selector._series_directory_cache._values) == 4


def test_derived_observation_copy_is_not_misrepresented_as_a_cached_raw_reference():
    result, cache, calls = source(), SeriesDirectoryCache(), []
    def projected(current):
        calls.append(True)
        return [{'id': 'projection'}], {'projection': [current.observations[0].model_copy(update={'unit': 'count'})]}
    for _ in range(2):
        _, lookup = cache.directory(result, projected)
        assert lookup['projection'][0].unit == 'count'
        assert lookup['projection'][0] is not result.observations[0]
    assert len(calls) == 2 and not cache._values


def test_reordered_source_observations_are_not_a_false_content_match(builds):
    result = source()
    first, lookup = selector.series_directory(result)
    result.observations.reverse()
    second, rebound = selector.series_directory(result)
    assert first == second and len(builds) == 2
    assert [item.id for item in next(iter(lookup.values()))] == [item.id for item in next(iter(rebound.values()))]


def test_source_row_composition_cache_keeps_full_matrix_snapshot_and_raw_references(builds):
    result = source()
    seed = result.observations[0]
    result.observations = []
    for period in ['FY2022', 'FY2023']:
        for label, value in [('Equipment', 40), ('Services', 30), ('Support', 20), ('Other', 10)]:
            item = seed.model_copy(deep=True)
            item.id, item.period = f'{label}-{period}', period
            item.metric_original = f'{label}: % of Total'
            item.value, item.raw_value = value, str(value)
            item.unit, item.raw_unit, item.currency, item.unit_scale = 'percent', '%', None, 1
            item.table_id = 'source-mix'
            item.dimensions = {'table_context': 'Reported sales mix'}
            item.evidence[0].table_id = 'source-mix'
            item.evidence[0].row_label, item.evidence[0].column_label = label, '% of Total'
            result.observations.append(item)
    first, _ = selector.series_directory(result)
    current = deepcopy(result)
    second, lookup = selector.series_directory(current)
    assert second == first and len(builds) == 1
    compositions = [row for row in second if row['visual_kind'] != 'series']
    assert any(row['periods'] == ['FY2022', 'FY2023'] and row['observation_count'] == 8 for row in compositions)
    assert any(row['periods'] == ['FY2023'] and row['observation_count'] == 4 for row in compositions)
    current_ids = {item.id: item for item in current.observations}
    for row in compositions:
        assert len(row['reported_points']) == len(lookup[row['id']]) == row['observation_count']
        assert all(item is current_ids[item.id] and item.category_dimensions == {}
                   for item in lookup[row['id']])
