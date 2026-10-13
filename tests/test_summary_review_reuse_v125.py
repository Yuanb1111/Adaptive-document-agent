import json
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.compact_summary import (
    CompactSummaryDraft, CompactSummaryReview, compact_input, expand_compact, generate_compact_summary)
from adaptive_document_agent.agent.summary_review_reuse import AcceptedPartReviews, part_review_signatures
from adaptive_document_agent.models.presentation import CompanyProfile
from tests.test_compact_summary_v111 import fixture, Reviewer


def test_repair_reviews_every_changed_binding_and_retains_only_unchanged_acceptances():
    result, review, draft = fixture(20)
    class Client(Reviewer):
        requested = []
        def generate_structured(self, messages, schema, **kwargs):
            if schema is CompactSummaryReview:
                payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                ids = {p['id'] for p in payload['source']['parts']}
                self.requested.append(ids)
                response = super().generate_structured(messages, schema, **kwargs)
                if len(self.requested) == 1:
                    response.parts[-1].accepted = False
                    response.parts[-1].reason = 'Explain the scheduling prerequisite.'
                return response
            if schema.__name__ == 'SummarySynthesisRevision':
                self.calls.append(schema.__name__)
                replacement = deepcopy(draft['pages'][1]['items'][0])
                replacement['text'] += ' Training precedes delivery.'
                return schema(replacements=[dict(item_id='g1_i0', replacement=replacement)])
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert company.summary_pages
    assert client.requested == [{f'part-{i}' for i in range(20)}, {f'part-{i}' for i in range(14, 20)}]
    assert len(review.plan_audits[-1]['retained_part_reviews']) == 14
    assert len(review.plan_audits[-1]['compact_semantic_review']['parts']) == 20


@pytest.mark.parametrize('change', ['text', 'label', 'title', 'placement', 'quote', 'source', 'refs'])
def test_reuse_is_invalidated_by_any_changed_copy_or_evidence(change):
    _, review, draft = fixture(2)
    _, catalog = compact_input(review)
    pages = expand_compact(CompactSummaryDraft.model_validate(draft), catalog, review)
    response = CompactSummaryReview(parts=[dict(part_id=p.id, accepted=True, reason='Verified.') for p in review.parts],
        opening_accepted=True, opening_reason='Verified.')
    ledger = AcceptedPartReviews()
    ledger.remember(response, part_review_signatures(review, pages), 1)
    assert len(ledger.retained(part_review_signatures(review, pages), {})) == 2
    if change in {'text', 'label'}: setattr(pages[0].items[0], change, 'Changed copy')
    elif change == 'title': pages[0].title = 'Changed context'
    elif change == 'placement': pages[0].placement = 'appendix'
    elif change == 'quote': pages[0].items[0].source_quote += 'Changed evidence'
    elif change == 'refs': pages[0].items[0].source_refs[0].fact_index += 1
    else:
        for p in review.parts: p.source_text += 'Changed qualification'
    assert not ledger.retained(part_review_signatures(review, pages), {})


def test_rejections_are_never_reused_as_acceptance():
    _, review, draft = fixture(1)
    _, catalog = compact_input(review)
    pages = expand_compact(CompactSummaryDraft.model_validate(draft), catalog, review)
    response = CompactSummaryReview(parts=[dict(part_id='part-0', accepted=False, reason='Missing qualification.')],
        opening_accepted=True, opening_reason='Verified.')
    ledger = AcceptedPartReviews()
    ledger.remember(response, part_review_signatures(review, pages), 1)
    assert not ledger.retained(part_review_signatures(review, pages), {})
