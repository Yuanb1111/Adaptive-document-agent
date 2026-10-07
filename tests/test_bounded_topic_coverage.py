"""Large catalogs must review every fact without losing accepted evidence."""
import json
import pytest
from adaptive_document_agent.agent.coverage_review_context import compact_context, batch_context, encode
from adaptive_document_agent.agent.topic_coverage_review import TopicCoverageReview, review_topic_coverage
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models import PresentationTopicSelection
from tests.test_topic_coverage_review import _fixture, _topic, _observation
from adaptive_document_agent.agent.presentation_topic_selector import series_directory


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
