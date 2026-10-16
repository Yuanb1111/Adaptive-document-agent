"""Accepted audience meanings constrain prose without relaxing source/meaning gates."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, compact_input, generate_compact_summary
from adaptive_document_agent.agent.summary_draft_protocol import SummaryDraftProtocolError
from adaptive_document_agent.models.presentation import CompanyProfile
from tests.test_compact_summary_v111 import fixture, Reviewer
from tests.test_total_file_budget_v130 import choose
from tests.test_summary_compression_v145 import DraftClient, paginate
from tests.test_summary_compression_protocol_v145 import FormatSequence


def scoped_fixture():
    result, review, _ = fixture(3)
    central = [part.source_text.strip() for part in review.parts]
    extra = ' An optional historical archive also describes office furniture and travel arrangements.'
    for part, text in zip(review.parts, central):
        part.source_text = text+extra+'\n'
        part.facts[0].text = part.facts[0].source_quote = part.source_text.strip()
    text = ''.join(part.source_text for part in review.parts)
    result.document.pages[0].text = review.source_blocks[0].text = text
    review.source_blocks[0].char_end = len(text)
    review.max_intro_slides = 1
    choose(result, review, selected=tuple(part.id for part in review.parts))
    _, catalog = compact_input(review)
    original = CompactSummaryDraft(pages=[dict(title='Scheduling service', items=[dict(
        label='Service prerequisite', text=part.source_text.strip(), fact_ids=[f'f{i}'],
        meaning_refs=[dict(part_id=part.id, meaning_index=0, summary_quote=part.source_text.strip())])])
        for i, part in enumerate(review.parts)])
    packed = original.model_copy(deep=True)
    packed.pages = [packed.pages[0].model_copy(update={'items': [page.items[0] for page in packed.pages]})]
    for item, text in zip(packed.pages[0].items, central):
        item.text = text
        item.meaning_refs[0].summary_quote = text
    return result, review, catalog, original, packed


class ScopeClient(Reviewer):
    def __init__(self, original, packed, *, missing_condition=False):
        super().__init__(original.model_dump(mode='json'))
        self.original, self.packed, self.missing_condition = original, packed, missing_condition
        self.writer_requests, self.reviewer_requests = [], []

    def generate_structured(self, messages, schema, **kwargs):
        if issubclass(schema, CompactSummaryDraft) or schema.__name__ == 'SummaryLayoutPages':
            self.writer_requests.append(deepcopy(messages))
            self.draft = (self.original if len(self.writer_requests) == 1 else self.packed).model_dump(mode='json')
        if schema.__name__ == 'SummarySynthesisRevision':
            raise ValueError('No independently approved correction exists for the missing training condition')
        response = super().generate_structured(messages, schema, **kwargs)
        if schema.__name__ == 'SummaryCoverageReview':
            self.reviewer_requests.append(deepcopy(messages))
            if self.missing_condition:
                response.parts[0].accepted = False
                response.parts[0].reason = 'The selected training prerequisite is missing.'
                response.parts[0].coverage[0].covered = False
                response.parts[0].coverage[0].summary_quote = ''
        return response


def test_selected_extra_source_copy_can_be_removed_with_all_ids_and_fresh_review():
    result, review, _, original, packed = scoped_fixture()
    client = ScopeClient(original, packed)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert len(company.summary_pages) == 1 and len(client.writer_requests) == 2
    assert len(client.reviewer_requests) == 1
    assert 'optional historical archive' not in ' '.join(item.text for page in company.summary_pages for item in page.items)
    audit = next(row for row in review.plan_audits if row.get('layout_attempts'))
    assert audit['fresh_complete_meaning_review'] is True
    assert {fid for page in audit['draft']['pages'] for item in page['items'] for fid in item['fact_ids']} == {'f0','f1','f2'}
    initial = client.writer_requests[0][0]['content']
    compression = ' '.join(message['content'] for message in client.writer_requests[1])
    assert 'NOT an additional audience checklist' in initial
    assert 'multiple compatible distinct required meanings' in initial
    assert 'Every separate item adds a labelled heading and spacing' in initial
    assert 'target 160-240' not in initial and 'paragraphs below 1200' not in initial
    assert 'MAY remove ONLY those unselected independent assertions' in compression
    assert 'Preserve every supported claim, source part' not in compression
    assert 'necessary condition' in client.reviewer_requests[0][0]['content']


def test_selected_scope_never_authorizes_a_missing_required_qualification():
    result, review, _, original, packed = scoped_fixture()
    packed.pages[0].items[0].text = 'Team AA supports scheduling.'
    client = ScopeClient(original, packed, missing_condition=True)
    with pytest.raises(ValueError):
        generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert 'SummaryCoverageReview' in client.calls
    assert not any(row.get('compact_digest') for row in review.plan_audits)


def test_selected_extra_removal_cannot_remove_original_fact_provenance():
    _, review, catalog, original, packed = scoped_fixture()
    packed.pages[0].items.pop()
    with pytest.raises(SummaryDraftProtocolError, match='removed protected source fact IDs'):
        paginate(DraftClient(packed), original, catalog, review, {})


def test_legacy_compression_keeps_complete_authored_claim_protection():
    _, review, catalog, original, packed = scoped_fixture()
    review.audience_part_ids = None
    review.audience_selection = {}
    packed.pages[0].items = [page.items[0] for page in original.pages]
    client = DraftClient(packed)
    paginate(client, original, catalog, review, {})
    rules = ' '.join(message['content'] for message in client.calls[0])
    assert 'Preserve every supported claim, source part and fact ID' in rules
    assert 'MAY remove ONLY those unselected independent assertions' not in rules
    payload = json.loads(client.calls[0][1]['content'].split('\n',1)[1].rsplit('\n',1)[0])
    assert payload['audience_scope'] == 'complete_authored_claims'


def test_legacy_initial_author_keeps_its_existing_paragraph_guidance():
    result, review, _ = fixture(3)
    class AuthorBoundary(RuntimeError):
        pass
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            self.messages = messages
            raise AuthorBoundary()
    client = Client()
    with pytest.raises(AuthorBoundary):
        generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert 'target 160-240 Latin-equivalent characters each' in client.messages[0]['content']
    assert 'prefer complete concise paragraphs below 1200' in client.messages[0]['content']


def test_format_recovery_preserves_the_original_audience_scope():
    _, review, catalog, original, packed = scoped_fixture()
    client = FormatSequence(['invalid', packed])
    paginate(client, original, catalog, review, {})
    assert len(client.calls) == 2
    assert 'semantic audience/content scope of the original instructions' in client.calls[1][0][-1]['content']
