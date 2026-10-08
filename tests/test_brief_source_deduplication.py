"""Brief corroboration preserves retained observations and source distinctions."""

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.services.brief_source_deduplication import deduplicate_brief_facts
from tests.test_pptx_export import _result


def _facts(change=None):
    result = _result()
    subset = [item.model_copy(deep=True) for item in result.observations[:2]]
    for item in subset:
        item.id += '-other-source'
        item.evidence[0].page = 42
        item.dimensions['table_context'] = 'Supplemental table'
    if change == 'value':
        subset[0].value += 1
    elif change == 'raw':
        subset[0].raw_value += '.0'
    elif change == 'scope':
        subset[0].entity = 'Different entity'
    elif change == 'unit':
        subset[0].unit = 'count'
    result.observations.extend(subset)
    complete = result.charts[0]
    partial = complete.model_copy(update={'id': 'partial', 'observation_ids': [o.id for o in subset]})
    return result, [{'chart': partial, 'text': 'Partial source', 'pages': {42}},
                    {'chart': complete, 'text': 'Complete source', 'pages': {234}}]


def test_exact_subset_shows_once_and_retains_every_source_and_observation():
    result, facts = _facts()
    before = result.model_dump_json()
    merged = deduplicate_brief_facts(facts, DocumentIndex(result.observations))
    assert len(merged) == 1
    assert merged[0]['chart'].id == 'chart-1'
    assert merged[0]['pages'] == {42, 234}
    assert result.model_dump_json() == before
    assert facts[0]['pages'] == {42}


@pytest.mark.parametrize('change', ['value', 'raw', 'scope', 'unit'])
def test_source_distinctions_remain_visible(change):
    result, facts = _facts(change)
    assert len(deduplicate_brief_facts(facts, DocumentIndex(result.observations))) == 2
