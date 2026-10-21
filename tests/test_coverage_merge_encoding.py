"""Large semantic merges keep all evidence through reversible metadata factoring."""

from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.coverage_merge_encoding import encode_merge_context
from adaptive_document_agent.agent.coverage_review_context import compact_context, encode, merge_context
from adaptive_document_agent.agent.coverage_delta_review import TopicCoverageDelta
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.agent.topic_coverage_review import review_topic_coverage
from adaptive_document_agent.models import PresentationTopicSelection
from tests.test_bounded_topic_coverage import context_fixture
from tests.test_coverage_delta_v147 import decisions, force_delta, payload
from tests.test_topic_coverage_review import _topic


def _fixture():
    result, _, annual, _, _, raw = context_fixture(extra=20)
    qualification = 'Literal source department and measurement scope; do not infer missing categories. ' * 15
    for observation in result.observations:
        observation.parent_section = qualification
        observation.dimensions['section'] = qualification
    directory, lookup = series_directory(result)
    raw['all_extracted_series'] = [[entry[key] for key in raw['series_columns']] for entry in directory]
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    return result, lookup, selected, raw


def _restore_metadata(wire):
    restored = deepcopy(wire)
    dictionaries = restored.pop('series_value_dictionaries', {})
    restored.pop('series_metadata_encoding', None)
    for row in restored['all_extracted_series']:
        for index, field in enumerate(restored['series_columns']):
            if field in dictionaries:
                row[index] = dictionaries[field][row[index]]
    return restored


def test_merge_dictionary_roundtrips_all_points_and_source_metadata_without_touching_input():
    _, lookup, selected, raw = _fixture()
    included = [sid for sid in lookup if sid not in selected.topics[0].series_ids]
    context = merge_context(compact_context(raw), selected, included, [])
    # A future metadata column is preserved without a fixed document schema.
    for row in context['all_extracted_series']:
        row['new_scope_metadata'] = {'literal': ['verbatim source condition'] * 12, 'valid': True}
    original_context = deepcopy(context)
    original = json.loads(encode(context))
    encoded = encode_merge_context(context)
    wire = json.loads(encoded)
    assert wire['series_value_dictionaries']
    assert not {'id', 'reported_points'} & wire['series_value_dictionaries'].keys()
    assert len(encoded) < len(encode(context)) * .6
    assert _restore_metadata(wire) == original
    assert context == original_context
    assert encode_merge_context(wire) == encoded


@pytest.mark.parametrize('compact_required', [False, True])
def test_complete_merge_below_budget_reaches_model_and_retains_explicit_omissions(monkeypatch, compact_required):
    from adaptive_document_agent.agent import topic_coverage_review as module
    force_delta(monkeypatch, size=8)
    result, lookup, selected, raw = _fixture()
    candidates = [sid for sid in lookup if sid not in selected.topics[0].series_ids]
    complete_context = merge_context(compact_context(raw), selected, candidates, [])
    # The source-rich merge used to fail before asking the model. Keep the
    # existing budget mechanism, using a synthetic boundary between encodings.
    original_size = len(encode(complete_context))
    budget = ((original_size + len(encode_merge_context(complete_context))) // 2
              if compact_required else original_size * 2)
    monkeypatch.setattr(module, 'MAX_REVIEW_CHARACTERS', budget)
    snapshot = result.model_dump(include={'observations', 'presentation_topics', 'charts'})
    class Gateway:
        def __init__(self):
            self.requests = []

        def generate_structured(self, messages, schema, **kwargs):
            data = payload(messages)
            self.requests.append(data)
            ids = data['series_requiring_coverage_decision']
            if schema is TopicCoverageDelta:
                return decisions(schema, ids, ids)
            assert len(messages[-1]['content']) < budget
            assert ('series_value_dictionaries' in data) is compact_required
            assert _restore_metadata(data)['all_extracted_series'] == json.loads(encode(complete_context))['all_extracted_series']
            # The semantic merger may reject proposed additions after seeing
            # their complete source facts; Python never chooses which to omit.
            return schema(topics=selected.topics,
                coverage_decisions=[item.model_dump() for item in decisions(TopicCoverageDelta, ids).coverage_decisions])
    gateway = Gateway()
    final = review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    audit = json.loads(result.validation_warnings[-1].message)
    assert result.validation_warnings[-1].code == 'presentation_topic_coverage_review'
    assert len(gateway.requests) == 4 and audit['calls_used'] == 4
    assert audit['merge']['context_characters'] <= budget
    assert len(audit['review']['coverage_decisions']) == len(candidates)
    assert all(item['decision'] == 'omit' and item['reason'] for item in audit['review']['coverage_decisions'])
    assert final.topics == selected.topics
    assert result.model_dump(include={'observations', 'presentation_topics', 'charts'}) == snapshot


def test_small_merge_avoids_larger_dictionary_envelope():
    context = {'series_columns': ['id', 'metric', 'reported_points'],
               'all_extracted_series': [['source', 'one exact label', [['FY2024', '12', 12.0]]]]}
    assert encode_merge_context(context) == encode(context)


def test_incompressible_merge_still_fails_closed_after_complete_delta_reviews(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review as module
    force_delta(monkeypatch, size=4)
    result, lookup, selected, raw = _fixture()
    candidates = [sid for sid in lookup if sid not in selected.topics[0].series_ids]
    context = merge_context(compact_context(raw), selected, candidates, [])
    monkeypatch.setattr(module, 'MAX_REVIEW_CHARACTERS', len(encode_merge_context(context)) - 500)
    class Gateway:
        def __init__(self):
            self.requested = []

        def generate_structured(self, messages, schema, **kwargs):
            assert schema is TopicCoverageDelta  # Oversized merge never reaches the provider.
            ids = payload(messages)['series_requiring_coverage_decision']
            self.requested.extend(ids)
            return decisions(schema, ids, ids)
    gateway = Gateway()
    final = review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    warning = result.validation_warnings[-1]
    audit = json.loads(warning.message)
    assert warning.code == 'presentation_topic_coverage_unresolved'
    assert 'reduction capacity' in audit['reason']
    assert not audit['unreviewed_series_ids']
    assert gateway.requested[:len(candidates)] == candidates
    assert final == selected and audit['merge']['reductions']
