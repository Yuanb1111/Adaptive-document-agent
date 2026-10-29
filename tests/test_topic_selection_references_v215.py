"""Request addresses never rewrite source content or confer semantic acceptance."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.topic_selection_references import (
    reference_input, restore_selection, selection_request,
)
from adaptive_document_agent.models import PresentationTopicSelection
from scripts.inspect_topic_request_size import restore_input
from tests.test_executive_brief import result_for


def fixture(count=3):
    ids = ['s0', *[f'presentation_series_{i:032x}' for i in range(count - 1)]]
    return dict(series_columns=['id', 'metric', 'source_pages'],
        all_extracted_series=[[sid, f'Literal source label {sid}', [i + 1]] for i, sid in enumerate(ids)],
        ratio_definitions=[dict(series_id=sid, definitions=[dict(text=f'Source definition {sid}')]) for sid in ids],
        source_row_qualifications=[dict(series_id=sid, notes=[f'Literal quoted ID {sid}']) for sid in ids],
        same_source_row_period_views=[dict(same_source_row=[dict(series_id=sid, periods=['6M2024'],
            internally_comparable_periods=['6M2024']) for sid in ids], scope_note='Do not combine bases.')])


def test_exact_address_roundtrip_preserves_all_facts_and_original_source_strings():
    original = fixture()
    before = deepcopy(original)
    wire, references = reference_input(original)
    assert restore_input(wire, references) == before and original == before
    assert 's0' not in references and references['s1'] == 's0'
    assert [row[1:] for row in wire['all_extracted_series']] == [row[1:] for row in original['all_extracted_series']]
    for field, content in [('ratio_definitions', 'definitions'), ('source_row_qualifications', 'notes')]:
        assert [row[content] for row in wire[field]] == [row[content] for row in original[field]]


def test_large_catalog_keeps_every_reference_and_small_catalog_stays_literal():
    encoded, references = selection_request(fixture(500))
    wire = json.loads(encoded)
    assert len(references) == len(wire['all_extracted_series']) == 500
    assert {row[0] for row in wire['all_extracted_series']} == set(references)
    encoded, references = selection_request(fixture())
    assert not references and 'presentation_series_' in encoded


def test_output_restores_only_addresses_and_unknown_references_stay_invalid():
    _, references = reference_input(fixture())
    result = result_for(['Literal evidence'])
    selection = PresentationTopicSelection(topics=[dict(id='topic', title='Keep s1 as audience text',
        question='What changed?', rationale='Source supports the question.',
        series_ids=['s1', 's2', 'not_in_catalog'])],
        omissions=[dict(series_id='s3', reason='A source-owned omission.')])
    restore_selection(selection, references, result)
    assert selection.topics[0].series_ids == ['s0', references['s2'], 'not_in_catalog']
    assert selection.omissions[0].series_id == references['s3']
    assert selection.topics[0].title == 'Keep s1 as audience text'
    assert json.loads(result.validation_warnings[-1].message)['references'] == references


def test_duplicate_identity_fails_without_relabeling_evidence():
    value = fixture()
    value['all_extracted_series'].append(deepcopy(value['all_extracted_series'][0]))
    with pytest.raises(ValueError, match='duplicate retained identities'):
        reference_input(value)
