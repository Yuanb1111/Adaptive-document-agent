"""Large catalogs must review every fact without losing accepted evidence."""
import json
import pytest
from adaptive_document_agent.agent.coverage_review_context import compact_context, batch_context, delta_context, encode
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


def test_distinct_new_binding_error_can_be_corrected_without_repeating_a_failure():
    from adaptive_document_agent.agent.topic_coverage_review import _review_batch
    from tests.test_topic_coverage_review import _review
    _, lookup, annual, interim, adverse, payload = context_fixture()
    current = PresentationTopicSelection(topics=[_topic(annual)])
    first = _review(annual, interim, adverse)
    first.topics = current.topics
    second = _review(annual, interim, adverse)
    second.topics[-1].series_ids = ['unknown-source']
    good = _review(annual, interim, adverse)
    class Gateway:
        def __init__(self): self.calls = 0
        def generate_structured(self, messages, model, **kwargs):
            self.calls += 1
            return [first, second, good][self.calls - 1]
    gateway, audit = Gateway(), {}
    revised, decisions = _review_batch(batch_context(compact_context(payload), current, [interim, adverse]),
        current, [interim, adverse], lookup, set(), gateway, PresentationTopicSelector._validate, audit)
    assert gateway.calls == 3
    assert set(decisions) == {interim, adverse}
    assert len({a['validation_error'] for a in audit['attempts'][:2]}) == 2
    assert 'validation_error' not in audit['attempts'][-1]


def test_topic_count_overflow_is_regrouped_with_full_source_context():
    from pydantic import ValidationError
    from adaptive_document_agent.agent.topic_coverage_review import _review_batch
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    from tests.test_topic_coverage_review import _review
    _, lookup, annual, interim, adverse, payload = context_fixture()
    current = PresentationTopicSelection(topics=[_topic(annual)])
    good = _review(annual, interim, adverse)
    raw = good.model_dump()
    raw['topics'] = raw['topics'] * 3
    class Gateway:
        def __init__(self): self.calls = []
        def generate_structured(self, messages, model, **kwargs):
            self.calls.append(messages)
            if len(self.calls) == 1:
                try:
                    model.model_validate(raw)
                except ValidationError as exc:
                    raise LLMStructuredOutputError('Invalid topic count',
                        response=LLMResponse(text=json.dumps(raw))) from exc
            assert messages[1] == self.calls[0][1]
            assert 'schema_errors' in messages[2]['content']
            return good
    gateway, audit = Gateway(), {}
    revised, decisions = _review_batch(batch_context(compact_context(payload), current, [interim, adverse]),
        current, [interim, adverse], lookup, set(), gateway, PresentationTopicSelector._validate, audit)
    assert len(gateway.calls) == 2 and len(revised.topics) == 3
    assert set(decisions) == {interim, adverse}
    assert json.loads(audit['attempts'][0]['invalid_response']) == raw


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


def test_batch_qualifications_follow_full_series_without_repeating_deferred_notes():
    _, _, annual, interim, adverse, payload = context_fixture()
    selection = PresentationTopicSelection(topics=[_topic(annual)])
    payload['source_row_qualifications'] = [
        {'series_id': sid, 'notes': ['Complete source qualification ' + sid]}
        for sid in (annual, interim, adverse)]
    compact = compact_context(payload)
    first = batch_context(compact, selection, [interim])
    second = batch_context(compact, selection, [adverse])
    assert first['source_row_qualifications'] == payload['source_row_qualifications'][:2]
    assert second['source_row_qualifications'] == [payload['source_row_qualifications'][i] for i in (0, 2)]
    assert len(compact['source_row_qualifications']) == 3


@pytest.mark.parametrize('changed_field', [None, 'value', 'unit_scale', 'audited_status', 'period'])
def test_duplicate_view_omission_is_reconciled_only_when_every_source_fact_matches(changed_field):
    from adaptive_document_agent.agent.topic_coverage_review import _validate_batch
    _, lookup, annual, _, _, _ = context_fixture()
    duplicates = [o.model_copy(deep=True, update={'id': 'duplicate-' + o.id}) for o in lookup[annual]]
    if changed_field:
        setattr(duplicates[-1], changed_field, {
            'value': 999, 'unit_scale': 1000, 'audited_status': 'UNAUDITED', 'period': 'FY2025'
        }[changed_field])
    lookup['duplicate'] = duplicates
    current = PresentationTopicSelection(topics=[_topic(annual)])
    reviewed = TopicCoverageReview(**current.model_dump(), coverage_decisions=[
        dict(series_id='duplicate', decision='omit', reason='No need for another view of the selected evidence.')])
    before = reviewed.model_dump()
    _, decisions, links = _validate_batch(reviewed, current, ['duplicate'], lookup, set(), PresentationTopicSelector._validate)
    assert decisions['duplicate'].decision == ('omit' if changed_field else 'include')
    assert ('duplicate' in links) == (changed_field is None)
    assert reviewed.model_dump() == before  # Keep the original semantic audit.
    if changed_field:
        reviewed.coverage_decisions[0].decision = 'include'
        with pytest.raises(ValueError, match='actually selected'):
            _validate_batch(reviewed, current, ['duplicate'], lookup, set(), PresentationTopicSelector._validate)


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
    monkeypatch.setattr(module, 'MAX_DELTA_DECISIONS', 1)
    # This tests a complete multi-batch transaction independently of the
    # production request budget; the budget rollback has its own test.
    assert 3 < len(candidates) <= module.MAX_REVIEW_BATCHES < module.MAX_REVIEW_CALLS

    class Gateway:
        calls = []
        def generate_structured(self, messages, response_model, **kwargs):
            source = next(m for m in messages if m['role'] == 'user'
                          and 'series_requiring_coverage_decision' in m['content'])
            data = json.loads(source['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            self.calls.append(data)
            assert len(encode(data)) <= limit
            ids = data['series_requiring_coverage_decision']
            if fail_second and len(self.calls) >= 2:
                ids = []  # A malformed review must roll back the first batch.
            return response_model(coverage_decisions=[
                {'series_id': sid, 'decision': 'omit', 'reason': 'This evidence does not alter the requested historical question.'}
                for sid in ids])
    gateway = Gateway()
    raw = result.model_dump(include={'observations', 'presentation_topics', 'charts'})
    selected = review_topic_coverage(selection, result, lookup, set(), payload, gateway, PresentationTopicSelector._validate)
    assert (2 <= len(gateway.calls) <= 3) if fail_second else len(gateway.calls) == len(candidates)
    requested = [sid for data in gateway.calls for sid in data['series_requiring_coverage_decision']]
    if not fail_second:
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
    monkeypatch.setattr(module,'MAX_DELTA_DECISIONS',1)
    monkeypatch.setattr(module,'MAX_REVIEW_CALLS',3)
    class Gateway:
        def __init__(self):self.calls=[]
        def generate_structured(self,messages,model,**kwargs):
            data=json.loads(messages[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]);self.calls.append(data)
            assert kwargs['max_tokens']==module.MAX_REVIEW_OUTPUT_TOKENS
            return model(coverage_decisions=[
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


def test_short_input_still_batches_decisions_to_fit_bounded_output(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review as module
    result, lookup, annual, interim, adverse, payload = context_fixture(extra=3)
    selection = PresentationTopicSelection(topics=[_topic(annual)])
    candidates = {sid for sid in lookup if sid != annual}
    monkeypatch.setattr(module, 'MAX_REVIEW_DECISIONS', 2)
    monkeypatch.setattr(module, 'MAX_DELTA_DECISIONS', 2)
    class Gateway:
        def __init__(self): self.requested = []
        def generate_structured(self, messages, response_model, **kwargs):
            data = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            ids = data['series_requiring_coverage_decision']
            assert len(ids) <= 2
            self.requested.extend(ids)
            return response_model(coverage_decisions=[
                {'series_id': sid, 'decision': 'omit', 'reason': 'Outside this model-selected historical question.'}
                for sid in ids])
    gateway = Gateway()
    review_topic_coverage(selection, result, lookup, set(), payload, gateway, PresentationTopicSelector._validate)
    assert set(gateway.requested) == candidates and len(gateway.requested) == len(candidates)
    assert result.validation_warnings[-1].code == 'presentation_topic_coverage_review'


def test_large_catalog_reviews_more_than_eight_batches_without_sampling(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review as module
    monkeypatch.setattr(module, 'MAX_REVIEW_DECISIONS', 16)
    monkeypatch.setattr(module, 'MAX_DELTA_DECISIONS', 16)
    result, lookup, annual, _, _, payload = context_fixture(extra=300)
    selection = PresentationTopicSelection(topics=[_topic(annual)])
    candidates = {sid for sid in lookup if sid != annual}
    class Gateway:
        def __init__(self):
            self.requested = []
            self.calls = 0
        def generate_structured(self, messages, model, **kwargs):
            data = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            ids = data['series_requiring_coverage_decision']
            self.calls += 1
            self.requested.extend(ids)
            return model(coverage_decisions=[
                dict(series_id=sid, decision='omit', reason='Outside the requested historical comparison scope.')
                for sid in ids])
    gateway = Gateway()
    review_topic_coverage(selection, result, lookup, set(), payload, gateway, PresentationTopicSelector._validate)
    assert gateway.calls > 8
    assert set(gateway.requested) == candidates
    assert len(gateway.requested) == len(candidates)
    assert result.validation_warnings[-1].code == 'presentation_topic_coverage_review'

@pytest.mark.parametrize('different_field,value', [('parent_section','Reconciliation'), ('period_type','instant')])
def test_binding_repair_exposes_scope_and_requires_an_action(different_field, value):
    from adaptive_document_agent.agent.topic_coverage_review import _review_batch
    from tests.test_topic_coverage_review import _review
    _, lookup, annual, interim, adverse, payload = context_fixture()
    for item in lookup[adverse]:
        setattr(item, different_field, value)
    current = PresentationTopicSelection(topics=[_topic(annual)])
    bad = _review(annual, interim, adverse)
    bad.topics = current.topics
    corrected = bad.model_copy(deep=True)
    for decision in corrected.coverage_decisions:
        decision.decision = 'omit'
        decision.reason = 'This distinct source definition is redundant for the selected question.'
    class Gateway:
        calls = []
        def generate_structured(self, messages, model, **kwargs):
            self.calls.append(messages)
            if len(self.calls) == 2:
                feedback=json.loads(messages[2]['content'].split('\n',1)[1].rsplit('\n',1)[0])
                assert set(feedback['unbound_include_series_ids']) == {interim, adverse}
                assert all(f[different_field] == value for f in feedback['included_but_unrepresented_facts'][adverse])
                assert 'add that exact series ID' in messages[3]['content']
                assert 'redundancy judgment is an omit reason' in messages[3]['content']
            return bad if len(self.calls) == 1 else corrected
    gateway=Gateway()
    revised, decisions = _review_batch(batch_context(compact_context(payload),current,[interim,adverse]),
        current,[interim,adverse],lookup,set(),gateway,PresentationTopicSelector._validate,{})
    assert revised.topics == current.topics
    assert all(d.decision == 'omit' for d in decisions.values())
    assert len(gateway.calls) == 2
