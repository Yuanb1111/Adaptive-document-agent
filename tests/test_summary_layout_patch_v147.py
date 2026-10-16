"""Layout transport locks identity and exposes physical costs without approving meaning."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, SummarySynthesisDraft, expand_compact
from adaptive_document_agent.agent.summary_layout_feedback import layout_feedback
from adaptive_document_agent.agent.summary_layout_patch import (
    apply_layout_patch, layout_patch_messages, layout_patch_schema,
)
from adaptive_document_agent.agent.summary_layout_geometry import physical_allocation
from adaptive_document_agent.agent.summary_theme_layout import pack_theme_pages
from tests.test_summary_compression_v145 import compression_fixture, DraftClient, paginate


@pytest.mark.parametrize('schema', [CompactSummaryDraft, SummarySynthesisDraft])
def test_layout_response_schema_exposes_only_pages_and_retains_page_constraints(schema):
    patch_schema = layout_patch_schema(schema)
    assert set(patch_schema.model_fields) == {'pages'}
    assert patch_schema.model_fields['pages'].metadata == schema.model_fields['pages'].metadata
    _, _, _, _, packed = compression_fixture()
    data = {'pages': packed.model_dump(mode='json')['pages']}
    assert patch_schema.model_validate(data)
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        patch_schema.model_validate(dict(data, name_quote='A different literal quotation'))
    data['pages'][0]['items'][0]['fact_ids'] = []
    with pytest.raises(ValidationError):
        patch_schema.model_validate(data)


def test_page_patch_cannot_rewrite_any_identity_value_or_its_literal_evidence():
    _, _, _, original, packed = compression_fixture()
    original.name, original.name_quote, original.name_page = '原有主体', 'Original Subject\n原有主体', 2
    original.stock_code, original.stock_code_quote, original.stock_code_page = '1234', 'Code 1234', 2
    before = deepcopy(original)
    patch = layout_patch_schema(type(original))(pages=packed.pages)
    revised = apply_layout_patch(original, patch, type(original))
    assert revised.pages == packed.pages
    assert revised.model_dump(exclude={'pages'}) == original.model_dump(exclude={'pages'})
    assert original == before


def test_successful_regrouping_uses_one_page_patch_and_does_not_replay_synthesis_history():
    _, review, catalog, original, packed = compression_fixture()
    original.name_quote = 'Locked evidence envelope which must not be reauthored'
    client, audit = DraftClient(packed), {}
    current, pages = paginate(client, original, catalog, review, audit)
    assert len(pages) == 1 and len(client.calls) == 1
    assert current.name_quote == original.name_quote
    request = client.calls[0]
    assert len(request) == 3
    assert original.name_quote not in json.dumps(request, ensure_ascii=False)
    payload = json.loads(request[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(payload['current_pages'][0]) == {'title', 'items'}
    assert {row['id'] for row in payload['source_facts']} == set(catalog)
    assert len(payload['layout_feedback']['meaning_inventory']) == 3
    assert all('meaning_refs' not in row for group in payload['layout_feedback']['groups']
               for row in group['paragraphs'])
    assert all(item['meaning_refs'] for page in payload['current_pages'] for item in page['items'])
    assert audit['layout_attempts'][0]['compression_contract']['editable_fields'] == ['pages']
    assert audit['layout_attempts'][0]['compression_contract']['historical_author_messages_replayed'] is False
    assert audit['layout_attempts'][-1]['layout_feedback']['semantic_approval'] is False


def test_feedback_reports_actual_physical_loads_and_group_start_costs():
    _, review, catalog, original, packed = compression_fixture()
    feedback = layout_feedback(original, pack_theme_pages(expand_compact(original, catalog, review)), review, catalog)
    allocation = feedback['physical_allocation']
    assert allocation['target_physical_slides'] == 1
    assert allocation['logical_body_groups'] == 3
    assert allocation['current_physical_slides'] == 3
    assert allocation['continuation_slots_after_group_starts'] == 0
    assert [group['current_physical_slides'] for group in feedback['groups']] == [1, 1, 1]
    assert [page['paragraphs'][0]['authored_item_ids'] for page in feedback['physical_pages']] == [
        ['g0_i0'], ['g1_i0'], ['g2_i0']]
    for page in feedback['physical_pages']:
        assert page['full_width_remaining_inches'] == pytest.approx(
            page['full_width_capacity_inches']-page['full_width_needed_inches'], abs=.000002)
    combined = layout_feedback(packed, pack_theme_pages(expand_compact(packed, catalog, review)), review, catalog)
    assert combined['physical_allocation']['current_physical_slides'] == 1
    assert combined['physical_pages'][0]['native_grid'] is not None
    assert 'alternative' in allocation['rule']


def test_initial_allocation_uses_same_fonts_capacity_and_hard_slide_cap():
    before = physical_allocation(5)
    assert before['target_physical_slides'] == 5
    assert before['continuation_slots_after_group_starts'] == 5
    assert before['body_font_pt'] == 16 and before['title_font_pt'] == 32
    assert before['current_physical_slides'] is None
    assert before['semantic_approval'] is False
