"""Missing selected assertions can consume the existing final compression, never acceptance."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, generate_compact_summary
from adaptive_document_agent.agent.summary_draft_protocol import SummaryDraftProtocolError
from adaptive_document_agent.agent.summary_writer_copy import address_only_copy
from adaptive_document_agent.models.presentation import CompanyProfile
from tests.test_compact_summary_v111 import Reviewer
from tests.test_summary_compression_v145 import DraftClient, compression_fixture, paginate


def request_payload(messages):
    return json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


def restoration_fixture():
    result, review, catalog, complete, packed = compression_fixture()
    initial = complete.model_copy(deep=True)
    initial.pages[0].items[0].text = 'Team AA supports scheduling.'
    initial.pages[0].items[0].meaning_refs.clear()
    rejected = packed.model_copy(deep=True)
    rejected.pages[0].items[0].text = 'An incomplete service snapshot.'
    rejected.pages[0].items[0].meaning_refs.clear()
    return result, review, catalog, initial, rejected, packed


def test_initial_missing_selected_copy_is_explicit_before_the_first_compression():
    _, review, catalog, initial, _, complete = restoration_fixture()
    audit, client = {}, DraftClient(complete)
    current, pages = paginate(client, initial, catalog, review, audit)
    assert current == complete and len(pages) == len(client.calls) == 1
    first = audit['layout_attempts'][0]
    assert first['authored_meaning_coverage']['expected_meaning_count'] == 3
    assert first['authored_meaning_coverage']['missing'] == [dict(part_id='part-0', meaning_index=0)]
    assert first['initial_authored_coverage_errors']
    data = request_payload(client.calls[0])
    assert data['authored_coverage_diagnostics']['missing'] == first['authored_meaning_coverage']['missing']
    assert {(row['part_id'], row['meaning_index']) for row in data['layout_feedback']['meaning_inventory']} == {
        ('part-0', 0), ('part-1', 0), ('part-2', 0)}
    assert 'staff training' in data['source_quotes'][0]['text']
    assert 'Restore already-selected assertions absent from existing copy' in client.calls[0][0]['content']
    assert 'Restore visible meaning' in client.calls[0][-1]['content']
    assert data['compression_round'] == 1 and data['compression_round_limit'] == 2


def test_missing_first_compression_uses_original_protected_copy_in_the_existing_final_round():
    _, review, catalog, initial, rejected, complete = restoration_fixture()
    initial.name, initial.name_quote, initial.name_page = 'Source name', 'Source name', 1
    audit, client = {}, DraftClient(rejected, complete)
    current, pages = paginate(client, initial, catalog, review, audit)
    # Only pages came from the response; the original identity is immutable.
    assert current.name == initial.name and current.name_quote == initial.name_quote
    assert current.name_page == initial.name_page and len(pages) == 1
    assert len(client.calls) == 2
    recovery = audit['layout_attempts'][1]
    assert recovery['status'] == 'source_invalid'
    assert recovery['compression_recovery']['original_meaning_completeness_assumed'] is False
    assert recovery['compression_recovery']['consumes_existing_final_compression'] is True
    data = request_payload(client.calls[1])
    assert data['current_pages'] == address_only_copy(initial.model_dump(mode='json')['pages'])
    assert data['rejected_compression']['pages'] == address_only_copy(rejected.model_dump(mode='json')['pages'])
    assert data['rejected_compression']['status'] == 'source_invalid'
    assert data['compression_round'] == data['compression_round_limit'] == 2
    assert data['authored_coverage_diagnostics']['missing'] == [dict(part_id='part-0', meaning_index=0)]
    assert 'Restore EVERY already-selected required meaning' in client.calls[1][-1]['content']
    assert 'not merely reference metadata' in client.calls[1][-1]['content']
    assert {fid for page in current.pages for item in page.items for fid in item.fact_ids} == {'f0', 'f1', 'f2'}
    assert [row['status'] for row in audit['layout_attempts']] == ['overflow', 'source_invalid', 'success']
    assert audit['layout_attempts'][-1]['authored_meaning_coverage']['structurally_complete'] is True
    assert audit['layout_attempts'][-1]['authored_meaning_coverage']['semantic_approval'] is False


@pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_owner', 'removed_fact', 'overflow'])
def test_last_restoration_candidate_still_fails_closed_without_another_compression(fault):
    _, review, catalog, initial, rejected, complete = restoration_fixture()
    final = complete.model_copy(deep=True)
    if fault == 'missing':
        final.pages[0].items[0].meaning_refs.clear()
    elif fault == 'unknown':
        final.pages[0].items[0].meaning_refs[0].meaning_index = 9
    elif fault == 'wrong_owner':
        final.pages[0].items[0].fact_ids = ['f1']
    elif fault == 'removed_fact':
        final.pages[0].items.pop()
    else:
        _, _, _, final, _ = compression_fixture()
    audit, client = {}, DraftClient(rejected, final)
    with pytest.raises(SummaryDraftProtocolError, match='source preservation|layout repair exhausted'):
        paginate(client, initial, catalog, review, audit)
    assert len(client.calls) == 2 and len(audit['layout_attempts']) == 3
    assert not any(row['status'] == 'success' for row in audit['layout_attempts'])


def test_filling_a_reference_without_restoring_the_assertion_still_needs_fresh_semantic_acceptance():
    result, review, _, initial, rejected, complete = restoration_fixture()
    false_coverage = complete.model_copy(deep=True)
    item = false_coverage.pages[0].items[0]
    item.text = 'Team AA supports scheduling.'
    item.meaning_refs[0].summary_quote = item.text
    class Client(Reviewer):
        def __init__(self):
            super().__init__({})
            self.writers, self.review_requests = [], []

        def generate_structured(self, messages, schema, **kwargs):
            if issubclass(schema, CompactSummaryDraft) or schema.__name__ == 'SummaryLayoutPages':
                self.writers.append(deepcopy(messages))
                value = address_only_copy([initial, rejected, false_coverage][len(self.writers)-1].model_dump(mode='json'))
                return schema.model_validate({'pages':value['pages']} if schema.__name__ == 'SummaryLayoutPages' else value)
            if schema.__name__ == 'SummarySynthesisRevision':
                raise ValueError('No independently approved repair exists for the missing selected condition.')
            response = super().generate_structured(messages, schema, **kwargs)
            if schema.__name__ == 'SummaryCoverageReview':
                self.review_requests.append(deepcopy(messages))
                verdict = next(row for row in response.parts if row.part_id == 'part-0')
                verdict.accepted = False
                verdict.reason = 'The selected staff training prerequisite is absent from visible copy.'
                verdict.coverage[0].covered = False
                verdict.coverage[0].summary_quote = ''
            return response
    client = Client()
    with pytest.raises(ValueError):
        generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert len(client.writers) == 3 and len(client.review_requests) == 1
    first = next(row for row in review.plan_audits if row.get('layout_attempts'))
    assert first['layout_attempts'][-1]['status'] == 'success'
    assert first['fresh_complete_meaning_review'] is True
    assert first['authored_meaning_coverage']['structurally_complete'] is True
    assert any(row['accepted'] is False for row in first['compact_semantic_review']['parts'])
    assert review.status == 'incomplete'
