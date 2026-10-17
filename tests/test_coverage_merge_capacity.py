"""Output capacity follows the full ledger without more calls or changed facts."""

from copy import deepcopy
import json

from adaptive_document_agent.agent.coverage_merge_capacity import MAX_MERGE_OUTPUT_TOKENS, merge_output_tokens
from adaptive_document_agent.agent.coverage_delta_review import TopicCoverageDelta
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_coverage_review import review_topic_coverage
from adaptive_document_agent.models import PresentationTopicSelection
from tests.test_bounded_topic_coverage import context_fixture
from tests.test_coverage_delta_v147 import decisions, force_delta, payload
from tests.test_topic_coverage_review import _topic


def test_small_complete_inventory_preserves_base_output_budget():
    assert merge_output_tokens({'topics': [], 'omissions': []}, []) == 8192


def test_large_complete_inventory_expands_output_capacity_without_mutation():
    selection = {'topics': [{'id': 'accepted', 'takeaway': 'A source-bound question. ' * 100}], 'omissions': []}
    inventory = [{'series_id': f'complete_source_{index}', 'decision': 'include',
                  'reason': 'Source-owned qualification ' * 10} for index in range(129)]
    original = deepcopy((selection, inventory))
    output = merge_output_tokens(selection, inventory)
    size = len(json.dumps({**selection, 'coverage_decisions': inventory},
                          ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    assert output == (size * 5 + 7) // 8 + 1024
    assert 8192 < output < MAX_MERGE_OUTPUT_TOKENS
    assert (selection, inventory) == original


def test_merge_output_capacity_has_an_absolute_ceiling():
    selection = {'topics': [], 'omissions': []}
    inventory = [{'series_id': str(index), 'decision': 'include', 'reason': '\u4fdd\u7559\u539f\u6587\u9650\u5b9a' * 60}
                 for index in range(200)]
    assert merge_output_tokens(selection, inventory) == MAX_MERGE_OUTPUT_TOKENS


def test_merge_uses_complete_inventory_budget_but_delta_calls_keep_base_budget(monkeypatch):
    force_delta(monkeypatch, size=8)
    result, lookup, annual, _, _, raw = context_fixture(extra=60)
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    candidates = [sid for sid in lookup if sid != annual]
    initial = [dict(series_id=sid, decision='include', reason='A complete source-bound material qualification. ' * 8)
               for sid in candidates]
    expected = merge_output_tokens(selected.model_dump(mode='json'), initial)
    assert expected > 8192
    class Gateway:
        def __init__(self):
            self.calls = 0

        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            ids = payload(messages)['series_requiring_coverage_decision']
            if schema is TopicCoverageDelta:
                assert kwargs['max_tokens'] == 8192
                return schema(coverage_decisions=[item for item in initial if item['series_id'] in ids])
            assert kwargs['max_tokens'] == expected
            return schema(topics=selected.topics,
                coverage_decisions=[item.model_dump() for item in decisions(TopicCoverageDelta, ids).coverage_decisions])
    gateway = Gateway()
    final = review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    audit = json.loads(result.validation_warnings[-1].message)
    assert result.validation_warnings[-1].code == 'presentation_topic_coverage_review'
    assert audit['merge']['requested_max_tokens'] == expected
    assert audit['calls_used'] == gateway.calls == len(audit['batches']) + 1
    assert final.topics == selected.topics
