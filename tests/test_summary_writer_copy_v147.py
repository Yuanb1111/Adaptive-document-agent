"""Writers choose meaning addresses; exact copy binding never proves meaning coverage."""
from copy import deepcopy
import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, SummarySynthesisDraft
from adaptive_document_agent.agent.summary_authored_coverage import authored_coverage_errors
from adaptive_document_agent.agent.summary_content_repair import SummarySynthesisRevision
from adaptive_document_agent.agent.summary_draft_protocol import author_draft
from adaptive_document_agent.agent.summary_layout_feedback import selected_meaning_source
from adaptive_document_agent.agent.summary_layout_patch import layout_patch_schema
from adaptive_document_agent.agent.summary_writer_copy import writer_schema, bind_writer_copy, address_only_copy
from tests.test_summary_compression_v145 import compression_fixture


@pytest.mark.parametrize('canonical', [CompactSummaryDraft, SummarySynthesisDraft,
    layout_patch_schema(CompactSummaryDraft), SummarySynthesisRevision])
def test_writer_schema_uses_only_strict_addresses_and_retains_operation_identity(canonical):
    schema = writer_schema(canonical)
    assert schema.__name__ == canonical.__name__ and issubclass(schema, canonical)
    refs = schema.model_json_schema()['$defs']['SummaryWriterMeaningRef']
    assert set(refs['properties']) == {'part_id', 'meaning_index'}
    assert refs['additionalProperties'] is False


def test_initial_author_binds_each_address_to_its_exact_current_paragraph():
    _, review, catalog, _, packed = compression_fixture()
    packed.name, packed.name_quote = '原有主体', 'Original Subject\n原有主体'
    value = address_only_copy(packed.model_dump(mode='json'))
    before = deepcopy(value)
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            return schema.model_validate(value)
    audit = {}
    current = author_draft(Client(), [], CompactSummaryDraft, audit)
    assert value == before
    assert current.model_dump(exclude={'pages'}) == packed.model_dump(exclude={'pages'})
    assert all(ref.summary_quote == item.text for page in current.pages for item in page.items for ref in item.meaning_refs)
    assert not authored_coverage_errors(current, selected_meaning_source(review), catalog, {})
    assert audit['writer_copy_binding']['semantic_approval'] is False


def test_stale_model_quote_is_not_an_accepted_field_and_is_never_fuzzy_matched():
    _, _, _, _, packed = compression_fixture()
    value = packed.model_dump(mode='json')
    value['pages'][0]['items'][0]['meaning_refs'][0]['summary_quote'] = 'Old paragraph text.'
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        writer_schema(CompactSummaryDraft).model_validate(value)


@pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_owner', 'duplicate'])
def test_copy_binding_never_invents_or_approves_a_meaning_mapping(fault):
    _, review, catalog, _, packed = compression_fixture()
    value = address_only_copy(packed.model_dump(mode='json'))
    refs = value['pages'][0]['items'][0]['meaning_refs']
    if fault == 'missing': refs.clear()
    elif fault == 'unknown': refs[0]['meaning_index'] = 999
    elif fault == 'wrong_owner': refs[0]['part_id'] = 'part-1'
    else: refs.append(deepcopy(refs[0]))
    wire = writer_schema(CompactSummaryDraft).model_validate(value)
    current, _ = bind_writer_copy(wire, CompactSummaryDraft)
    assert authored_coverage_errors(current, selected_meaning_source(review), catalog, {})


def test_address_transport_keeps_each_split_paragraph_distinct_and_all_constraints():
    _, _, _, _, packed = compression_fixture()
    value = address_only_copy(packed.model_dump(mode='json'))
    item = value['pages'][0]['items'][0]
    other = deepcopy(item)
    other['text'] = 'A different current paragraph retaining the same writer-selected mapping.'
    value['pages'][0]['items'].append(other)
    current, count = bind_writer_copy(writer_schema(CompactSummaryDraft).model_validate(value), CompactSummaryDraft)
    first, second = current.pages[0].items[0], current.pages[0].items[-1]
    assert first.meaning_refs[0].summary_quote == first.text
    assert second.meaning_refs[0].summary_quote == second.text != first.text
    assert count == 4
    item['text'] = 'x'*6001
    with pytest.raises(ValidationError): writer_schema(CompactSummaryDraft).model_validate(value)
