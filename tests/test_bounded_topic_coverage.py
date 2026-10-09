"""Large catalogs must review every fact without losing accepted evidence."""
import json
import pytest
from adaptive_document_agent.agent.coverage_review_context import compact_context, batch_context, encode
from adaptive_document_agent.agent.topic_coverage_review import TopicCoverageReview, review_topic_coverage
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models import PresentationTopicSelection
from tests.test_topic_coverage_review import _fixture, _topic, _observation
from adaptive_document_agent.agent.presentation_topic_selector import series_directory


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_bounded_semantic_repair_retains_failed_attempt_and_all_facts(repair_succeeds):
    from adaptive_document_agent.agent.topic_coverage_review import _review_batch
    from tests.test_topic_coverage_review import _review
    result, lookup, annual, interim, adverse, payload = context_fixture()
    current = PresentationTopicSelection(topics=[_topic(annual)])
    context = batch_context(compact_context(payload), current, [interim, adverse])
    bad = _review(annual, interim, adverse)
    bad.topics = current.topics
    good = _review(annual, interim, adverse)
    class Gateway:
        calls = []
        def generate_structured(self, messages, model, **kwargs):
            self.calls.append(messages)
            return bad if len(self.calls) == 1 or not repair_succeeds else good
    gateway, audit = Gateway(), {}
    raw = result.model_dump()
    if repair_succeeds:
        revised, decisions = _review_batch(context, current, [interim, adverse], lookup,
            set(), gateway, PresentationTopicSelector._validate, audit)
        assert {sid for t in revised.topics for sid in t.series_ids} == {annual, interim, adverse}
        assert set(decisions) == {interim, adverse}
        assert set(audit['representation_links']) == {interim, adverse}
    else:
        with pytest.raises(ValueError, match='actually selected'):
            _review_batch(context, current, [interim, adverse], lookup,
                set(), gateway, PresentationTopicSelector._validate, audit)
    assert len(gateway.calls) == len(audit['attempts']) == 2
    assert gateway.calls[0][1] == gateway.calls[1][1]
    assert 'validation_error' in audit['attempts'][0]
    feedback = json.loads(gateway.calls[1][2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    missing = feedback['included_but_unrepresented_facts']
    assert set(missing) == {interim, adverse}
    assert [fact['raw_value'] for fact in missing[interim]] == [o.raw_value for o in lookup[interim]]
    assert result.model_dump() == raw


def test_dictionary_and_period_views_roundtrip_without_touching_source_text():
    result, lookup, annual, interim, adverse, payload = context_fixture(extra=20)
    from adaptive_document_agent.agent.topic_coverage_review import source_period_views
    payload['same_source_row_period_views'] = source_period_views(lookup)
    compact = compact_context(payload)
    current = PresentationTopicSelection(topics=[_topic(annual)])
    context = batch_context(compact, current, [interim, adverse])
    original = json.loads(json.dumps(context))
    encoded = json.loads(encode(context))
    assert context == original
    assert encoded['current_selection'] == current.model_dump(mode='json')
    catalog = encoded['complete_series_catalog']
    for row in catalog:
        for i, field in enumerate(encoded['catalog_columns']):
            if field in encoded.get('catalog_value_dictionaries', {}):
                row[i] = encoded['catalog_value_dictionaries'][field][row[i]]
    assert catalog == context['complete_series_catalog']
    restored = [{'scope_note': encoded['period_view_scope_notes'][note],
                 'same_source_row': [dict(zip(encoded['period_view_entry_columns'], row)) for row in rows]}
                for note, rows in encoded['same_source_row_period_views']]
    assert restored == context['same_source_row_period_views']
    fresh = json.loads(encode(context))
    assert json.loads(encode(fresh)) == fresh


def test_future_period_view_fields_remain_literal():
    view = {'scope_note': 'Keep different source durations separate.',
            'same_source_row': [{'series_id': 'source', 'periods': ['FY2023'],
                                 'internally_comparable_periods': False, 'new_source_qualification': 'Unaudited'}]}
    encoded = json.loads(encode({'same_source_row_period_views': [view]}))
    assert encoded['same_source_row_period_views'] == [view]
    assert 'period_view_encoding' not in encoded


def context_fixture(extra=0):
    result, directory, lookup, annual, interim, adverse = _fixture()
    for index in range(extra):
        result.observations.extend([_observation(f'Constraint {chr(65+index)}', 'FY2022', 20),
                                    _observation(f'Constraint {chr(65+index)}', 'FY2023', 60)])
    directory, lookup = series_directory(result)
    columns = list(directory[0])
    payload = {'series_columns': columns,
        'reported_point_columns': ['observation_id', 'period', 'raw_value', 'value', 'unit_scale',
            'period_basis', 'period_type', 'period_start', 'period_end', 'definition_basis',
            'audited_status', 'validation_status', 'source_pages'],
        'all_extracted_series': [[entry[k] for k in columns] for entry in directory]}
    return result, lookup, annual, interim, adverse, payload


def test_compaction_retains_every_numeric_point_and_scope():
    result, lookup, annual, interim, adverse, payload = context_fixture()
    original = json.loads(json.dumps(payload))
    compact = compact_context(payload)
    for row in compact['all_extracted_series']:
        points = [{**row['point_constants'], **dict(zip(row['point_columns'], point))}
                  for point in row['reported_points']]
        originals = next(entry for entry in payload['all_extracted_series'] if entry[0] == row['id'])
        raw = originals[payload['series_columns'].index('reported_points')]
        expected = [dict(zip(payload['reported_point_columns'][1:], point[1:])) for point in raw]
        assert points == expected
    assert payload == original
    wire = json.loads(encode(compact))
    for row in wire['all_extracted_series']:
        entry = dict(zip(wire['series_columns'], row))
        constants = {wire['point_field_names'][index]: value for index, value in entry['point_constants']}
        variable = [wire['point_field_names'][index] for index in entry['point_columns']]
        points = [{**constants, **dict(zip(variable, point))} for point in entry['reported_points']]
        originals = next(row for row in payload['all_extracted_series'] if row[0] == entry['id'])
        raw = originals[payload['series_columns'].index('reported_points')]
        assert points == [dict(zip(payload['reported_point_columns'][1:], point[1:])) for point in raw]


@pytest.mark.parametrize('fail_second', [False, True])
def test_batched_review_is_complete_and_transactional(monkeypatch, fail_second):
    from adaptive_document_agent.agent import topic_coverage_review as module
    result, lookup, annual, interim, adverse, payload = context_fixture(extra=3)
    selection = PresentationTopicSelection(topics=[_topic(annual)])
    payload['current_selection'] = selection.model_dump(mode='json')
    payload['review_scope'] = 'All available series with evidence not represented in the current selected topics.'
    candidates = [sid for sid in lookup if sid != annual]
    payload['series_requiring_coverage_decision'] = candidates
    compact = compact_context(payload)
    # Force exactly one full candidate per request, without truncating its data.
    limit = max(len(encode(batch_context(compact, selection, [sid]))) for sid in candidates) + 5
    assert len(encode(batch_context(compact, selection, [interim, adverse]))) > limit
    monkeypatch.setattr(module, 'MAX_REVIEW_CHARACTERS', limit)
    # This tests a complete multi-batch transaction independently of the
    # production request budget; the budget rollback has its own test.
    assert 3 < len(candidates) <= module.MAX_REVIEW_BATCHES < module.MAX_REVIEW_CALLS

    class Gateway:
        calls = []
        def generate_structured(self, messages, response_model, **kwargs):
            data = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            self.calls.append(data)
            assert len(encode(data)) <= limit
            ids = data['series_requiring_coverage_decision']
            if fail_second and len(self.calls) == 2:
                ids = []  # A malformed review must roll back the first batch.
            return TopicCoverageReview(**data['current_selection'], coverage_decisions=[
                {'series_id': sid, 'decision': 'omit', 'reason': 'This evidence does not alter the requested historical question.'}
                for sid in ids])
    gateway = Gateway()
    raw = result.model_dump(include={'observations', 'presentation_topics', 'charts'})
    selected = review_topic_coverage(selection, result, lookup, set(), payload, gateway, PresentationTopicSelector._validate)
    assert len(gateway.calls) == (2 if fail_second else len(candidates))
    requested = [sid for data in gateway.calls for sid in data['series_requiring_coverage_decision']]
    assert len(requested) == len(set(requested))
    if not fail_second:
        assert set(requested) == set(candidates)
    assert result.model_dump(include={'observations', 'presentation_topics', 'charts'}) == raw
    assert selection.omissions == []
    warning = result.validation_warnings[-1]
    if fail_second:
        assert selected == selection
        assert warning.code == 'presentation_topic_coverage_unresolved'
    else:
        assert warning.code == 'presentation_topic_coverage_review'
        audit = json.loads(warning.message)
        assert len(audit['review']['coverage_decisions']) == len(candidates)
        assert {o.series_id for o in selected.omissions} == set(candidates)


def test_call_budget_exhaustion_rolls_back_partial_review(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review as module
    result,lookup,annual,interim,adverse,payload=context_fixture(extra=3)
    selection=PresentationTopicSelection(topics=[_topic(annual)])
    candidates=[sid for sid in lookup if sid!=annual]
    payload.update(current_selection=selection.model_dump(mode='json'),series_requiring_coverage_decision=candidates)
    payload['review_scope']='All available series with evidence not represented in the current selected topics.'
    compact=compact_context(payload)
    limit=max(len(encode(batch_context(compact,selection,[sid]))) for sid in candidates)+5
    monkeypatch.setattr(module,'MAX_REVIEW_CHARACTERS',limit)
    monkeypatch.setattr(module,'MAX_REVIEW_CALLS',3)
    class Gateway:
        def __init__(self):self.calls=[]
        def generate_structured(self,messages,model,**kwargs):
            data=json.loads(messages[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]);self.calls.append(data)
            assert kwargs['max_tokens']==module.MAX_REVIEW_OUTPUT_TOKENS
            return TopicCoverageReview(**data['current_selection'],coverage_decisions=[
                dict(series_id=sid,decision='omit',reason='Outside the requested question') for sid in data['series_requiring_coverage_decision']])
    gateway=Gateway()
    revised=review_topic_coverage(selection,result,lookup,set(),payload,gateway,PresentationTopicSelector._validate)
    assert len(gateway.calls)==module.MAX_REVIEW_CALLS==3 and revised==selection
    warning=result.validation_warnings[-1]
    assert warning.code=='presentation_topic_coverage_unresolved'
    assert 'budget exhausted' in warning.message
    assert json.loads(warning.message)['unreviewed_series_ids']

def test_compaction_preserves_category_to_value_mapping_in_matrix_dimensions():
    _, _, _, _, _, payload = context_fixture()
    mapping = [{'metric': 'Category A', 'period': 'FY2023', 'raw_value': '60'},
               {'metric': 'Category B', 'period': 'FY2023', 'raw_value': '40'}]
    payload['all_extracted_series'][0][payload['series_columns'].index('dimensions')] = {'reported_values': mapping}
    compact = compact_context(payload)
    assert compact['all_extracted_series'][0]['dimensions']['reported_values'] == mapping
