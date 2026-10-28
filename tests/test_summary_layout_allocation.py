"""The final existing repair can relocate complete copy without skipping review."""
from collections import Counter
from concurrent.futures import CancelledError
from threading import Event

import pytest

from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft, expand_compact
from adaptive_document_agent.agent.summary_layout_allocation import allocation_choices, choose_allocation
from adaptive_document_agent.agent.summary_layout_choices import layout_choices
from adaptive_document_agent.agent.summary_layout_feedback import layout_feedback
from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
from adaptive_document_agent.agent.summary_draft_protocol import SummaryDraftProtocolError
from tests.test_summary_compression_v145 import compression_fixture, DraftClient


def fixture():
    result, review, catalog, _, packed = compression_fixture()
    review.max_intro_slides = 2
    from tests.test_total_file_budget_v130 import choose
    choose(result, review, selected=tuple(part.id for part in review.parts))
    items = packed.pages[0].items
    for item, repetitions, label in zip(items, [12, 6, 6], ['Overview', 'Operating conditions', 'Delivery']):
        item.text = ' '.join([item.text] * repetitions)
        item.label = label
        item.meaning_refs[0].summary_quote = item.text
    values = [item.model_dump(mode='json') for item in items]
    draft = SummarySynthesisDraft(pages=[dict(title='Service overview', items=values[:2]),
                                        dict(title='Delivery requirements', items=values[2:])])
    return result, review, catalog, draft


class Client(DraftClient):
    def __init__(self, draft, response=None):
        super().__init__(draft)
        self.response = response or dict(choice='transfer_0')
        self.operations = []

    def generate_structured(self, messages, schema, **kwargs):
        self.operations.append(schema.__name__)
        if schema.__name__ == 'SummaryLayoutAllocation':
            self.calls.append(messages)
            assert kwargs['allow_repair'] is False
            return schema.model_validate(self.response)
        return super().generate_structured(messages, schema, **kwargs)


def run(client, draft, catalog, review, audit, **kwargs):
    return paginate_draft(client, draft, catalog, review, [], audit, expand_compact, SummarySynthesisDraft, **kwargs)


def test_transfer_fits_when_within_group_choices_cannot_and_preserves_every_item():
    _, review, catalog, draft = fixture()
    before = draft.model_dump_json(), review.model_dump_json()
    assert not layout_choices(draft, catalog, review, expand_compact)
    # expand_compact has an existing decision annotation side effect; the new
    # enumeration itself must leave the review and original draft untouched.
    review_before = review.model_dump_json()
    options = allocation_choices(draft, catalog, review, expand_compact)
    assert options and all((row['source'], row['item']) != (0, 0) for row in options.values())
    assert review.model_dump_json() == review_before
    client, audit = Client(draft), {}
    revised, pages = run(client, draft, catalog, review, audit)
    assert [a['layout_feedback']['score']['body_slides'] for a in audit['layout_attempts']] == [3, 3, 2]
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutAllocation']
    assert Counter(i.model_dump_json() for p in revised.pages for i in p.items) == Counter(
        i.model_dump_json() for p in draft.pages for i in p.items)
    assert draft.model_dump_json() == before[0]
    assert revised.pages[0].items[0] == draft.pages[0].items[0]
    assert revised.model_dump(exclude={'pages'}) == draft.model_dump(exclude={'pages'})
    assert review.status == 'incomplete' and len(pages) == 2
    assert audit['layout_attempts'][1]['lossless_layout_allocation']['semantic_approval'] is False
    assert 'independent source and per-meaning review' in client.calls[-1][0]['content']


@pytest.mark.parametrize('response', [dict(choice='keep'), dict(choice='transfer_0', destination_title='W'*65)])
def test_refusal_or_overflowing_new_title_still_fails_without_extra_retries(response):
    _, review, catalog, draft = fixture()
    client, audit = Client(draft, response), {}
    with pytest.raises(SummaryDraftProtocolError, match='layout repair exhausted'):
        run(client, draft, catalog, review, audit)
    assert len(client.calls) == 2 and len(audit['layout_attempts']) == 3
    assert review.max_intro_slides == 2 and review.status == 'incomplete'


@pytest.mark.parametrize('response', [dict(choice='unknown'), dict(choice='keep', source_title='Changed'),
    dict(choice='transfer_0', name='New identity'), dict(choice='transfer_0', replacement={'pages': []})])
def test_invalid_allocation_cannot_mutate_copy(response):
    _, review, catalog, draft = fixture()
    before = draft.model_dump_json()
    audit = dict(layout_feedback=layout_feedback(draft, None, review, catalog), errors=[],
                 compression_round=2, compression_round_limit=2)
    with pytest.raises(ValueError):
        choose_allocation(Client(draft, response), draft, catalog, review, audit,
            allocation_choices(draft, catalog, review, expand_compact), SummarySynthesisDraft)
    assert draft.model_dump_json() == before
    assert audit['lossless_layout_allocation']['status'] == 'failed'


def test_unavailable_budget_bounded_search_and_cancellation_never_choose_automatically(monkeypatch):
    from adaptive_document_agent.agent import summary_layout_allocation as allocation
    _, review, catalog, draft = fixture()
    review.max_intro_slides = 1
    assert not allocation_choices(draft, catalog, review, expand_compact)
    review.max_intro_slides = 2
    monkeypatch.setattr(allocation, 'MAX_TRANSFER_PROBES', 0)
    assert not allocation_choices(draft, catalog, review, expand_compact)
    client, event = Client(draft), Event()
    event.set()
    with pytest.raises(CancelledError):
        choose_allocation(client, draft, catalog, review, {}, {}, SummarySynthesisDraft, cancelled=event)
    with pytest.raises(SummaryDraftProtocolError, match='Additive omission correction'):
        run(client, draft, catalog, review, {}, allow_rewrite=False)
    assert not client.calls


@pytest.mark.parametrize('damage', ['meaning', 'fact', 'mixed'])
def test_replacement_escape_hatch_cannot_bypass_source_checks(damage):
    from adaptive_document_agent.agent.summary_layout_allocation import transferred_draft
    from adaptive_document_agent.agent.summary_writer_copy import address_only_copy
    _, review, catalog, draft = fixture()
    replacement = transferred_draft(draft, 0, 1, 1)
    if damage == 'meaning':
        replacement.pages[0].items[0].meaning_refs.clear()
    elif damage == 'fact':
        replacement.pages[0].items[0].fact_ids.append('unknown')
    response = dict(choice='transfer_0' if damage == 'mixed' else 'keep',
                    replacement=dict(pages=address_only_copy(replacement.model_dump(mode='json')['pages'])))
    client = Client(draft, response)
    with pytest.raises(ValueError, match='source preservation|also replace'):
        run(client, draft, catalog, review, {})
    assert len(client.calls) == 2 and review.status == 'incomplete'


def test_regrouping_success_still_reaches_fresh_independent_review(monkeypatch):
    from adaptive_document_agent.agent import compact_summary
    from adaptive_document_agent.models.presentation import CompanyProfile
    result, review, _, draft = fixture()
    monkeypatch.setattr(compact_summary, 'author_draft', lambda *args, **kwargs: draft)
    def independent_review(*args, **kwargs):
        raise RuntimeError('independent reviewer reached')
    monkeypatch.setattr(compact_summary, 'review_compact', independent_review)
    client = Client(draft)
    with pytest.raises(RuntimeError, match='independent reviewer reached'):
        compact_summary.generate_compact_summary(client, result, review, CompanyProfile(summary_review=review),
                                                draft_schema=SummarySynthesisDraft)
    assert review.plan_audits[-1]['fresh_complete_meaning_review'] is True
    assert review.status == 'incomplete'
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutAllocation']


def test_local_only_gateway_records_single_allocation_and_native_output_agrees():
    from pptx import Presentation
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName, PrivacyMode
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    from adaptive_document_agent.services.presentation_brief import BriefItem, render_profile
    _, review, catalog, draft = fixture()
    provider = MockLLMClient([dict(choice='transfer_0')])
    gateway = LLMGateway(provider, LLMSettings(provider=ProviderName.MOCK, privacy_mode=PrivacyMode.LOCAL_ONLY))
    record = dict(layout_feedback=layout_feedback(draft, None, review, catalog), errors=[],
                  compression_round=2, compression_round_limit=2)
    revised = choose_allocation(gateway, draft, catalog, review, record,
        allocation_choices(draft, catalog, review, expand_compact), SummarySynthesisDraft)
    _, pages = run(Client(draft), revised, catalog, review, {}, allow_rewrite=False)
    deck, rendered = Presentation(_resolve_template_path()), []
    for page in pages:
        rendered.extend(render_profile(deck, page.title, [BriefItem(i.label, i.text, i.source_pages) for i in page.items]))
    assert len(rendered) == len(pages) == 2
    assert ''.join(s.text for slide in rendered for s in slide.shapes if s.name == 'brief:body') == ''.join(
        item.text for page in pages for item in page.items)
    assert len(provider.calls) == 1 and gateway.usage[0]['operation'] == 'SummaryLayoutAllocation'
