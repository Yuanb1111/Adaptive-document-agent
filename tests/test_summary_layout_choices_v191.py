"""A stalled compression can select measured full-copy layouts, never skip review."""
from copy import deepcopy
from threading import Event
from concurrent.futures import CancelledError

import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, expand_compact
from adaptive_document_agent.agent.summary_authored_coverage import authored_coverage_errors
from adaptive_document_agent.agent.summary_draft_protocol import SummaryDraftProtocolError
from adaptive_document_agent.agent.summary_layout_choices import inline_group, layout_choices, choose_layout
from adaptive_document_agent.agent.summary_layout_feedback import selected_meaning_source, compression_binding_errors
from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
from tests.test_summary_compression_v145 import compression_fixture, DraftClient


def fixture():
    result, review, catalog, _, draft = compression_fixture()
    review.max_intro_slides = 2
    from tests.test_total_file_budget_v130 import choose
    choose(result, review, selected=tuple(part.id for part in review.parts))
    for index, item in enumerate(draft.pages[0].items):
        item.label = ['Scheduling', 'Delivery', 'Training'][index]
        item.text = ' '.join([item.text] * 7)
        item.meaning_refs[0].summary_quote = item.text
    return review, catalog, draft


class Client(DraftClient):
    def __init__(self, draft, choice='inline'):
        super().__init__(draft)
        self.choice, self.operations = choice, []

    def generate_structured(self, messages, schema, **kwargs):
        self.operations.append(schema.__name__)
        if schema.__name__ == 'SummaryLayoutChoice':
            self.calls.append(deepcopy(messages))
            assert kwargs['allow_repair'] is False
            return schema.model_validate({key: self.choice for key in schema.model_fields
                                          if key != 'replacement'})
        return super().generate_structured(messages, schema, **kwargs)


def test_stalled_rewrite_uses_second_round_for_a_measured_lossless_choice():
    review, catalog, draft = fixture()
    snapshot = draft.model_dump()
    audit, client = {}, Client(draft)
    revised, pages = paginate_draft(client, draft, catalog, review, [], audit,
        expand_compact, CompactSummaryDraft)
    assert len(pages) == 2
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutChoice']
    assert [r['status'] for r in audit['layout_attempts']] == ['overflow', 'overflow', 'success']
    assert draft.model_dump() == snapshot
    assert not compression_binding_errors(revised, draft, catalog)
    assert not authored_coverage_errors(revised, selected_meaning_source(review), catalog, {})
    original_items = draft.pages[0].items
    combined = revised.pages[0].items[0]
    assert combined.label == original_items[0].label
    assert combined.text == ' '.join((i.label + ': ' if n else '') + i.text
                                    for n, i in enumerate(original_items))
    assert [r.model_dump() for r in combined.meaning_refs] == [
        r.model_dump() for i in original_items for r in i.meaning_refs]
    assert combined.fact_ids == list(dict.fromkeys(f for i in original_items for f in i.fact_ids))
    assert revised.model_dump(exclude={'pages'}) == draft.model_dump(exclude={'pages'})
    choice = audit['layout_attempts'][1]['lossless_layout_choice']
    assert choice['semantic_approval'] is False and choice['additional_rewrite_round'] is False
    assert review.status == 'incomplete'
    assert 'independent source and meaning review' in client.calls[-1][0]['content']
    assert 'untrusted DATA' in client.calls[-1][0]['content']
    assert all(p.compact for p in pages)


def test_semantic_refusal_still_fails_with_the_original_hard_page_cap():
    review, catalog, draft = fixture()
    client, audit = Client(draft, 'keep'), {}
    with pytest.raises(SummaryDraftProtocolError, match='layout repair exhausted'):
        paginate_draft(client, draft, catalog, review, [], audit, expand_compact, CompactSummaryDraft)
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutChoice']
    assert len(audit['layout_attempts']) == 3 and review.max_intro_slides == 2


def test_impossible_menu_is_not_sent_and_missing_meaning_cannot_enter_menu():
    review, catalog, draft = fixture()
    review.max_intro_slides = 1
    assert layout_choices(draft, catalog, review, expand_compact) == {}
    review.max_intro_slides = 2
    invalid = draft.model_copy(deep=True)
    invalid.pages[0].items[0].meaning_refs = []
    audit, client = {}, Client(invalid)
    client.drafts.append(invalid)
    with pytest.raises(SummaryDraftProtocolError, match='source preservation'):
        paginate_draft(client, draft, catalog, review, [], audit, expand_compact, CompactSummaryDraft)
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutPages']


def test_no_rewrite_mode_never_calls_a_layout_selector():
    review, catalog, draft = fixture()
    client = Client(draft)
    with pytest.raises(SummaryDraftProtocolError, match='Additive omission correction'):
        paginate_draft(client, draft, catalog, review, [], {}, expand_compact,
                       CompactSummaryDraft, allow_rewrite=False)
    assert client.calls == []


def test_cancellation_and_invalid_choices_cannot_apply_a_patch():
    review, catalog, draft = fixture()
    choices = layout_choices(draft, catalog, review, expand_compact)
    event = Event()
    event.set()
    client = Client(draft)
    with pytest.raises(CancelledError):
        choose_layout(client, draft, catalog, review, {}, choices, CompactSummaryDraft, cancelled=event)
    assert client.calls == []
    from adaptive_document_agent.agent.summary_layout_feedback import layout_feedback
    record = dict(layout_feedback=layout_feedback(draft, None, review, catalog))
    with pytest.raises(ValueError):
        choose_layout(Client(draft, 'delete'), draft, catalog, review, record, choices, CompactSummaryDraft)
    assert record['lossless_layout_choice']['status'] == 'failed'


def test_inline_copy_preserves_duplicate_ownership_but_not_duplicate_exact_refs():
    _, _, draft = fixture()
    page = draft.pages[0]
    page.items[1].meaning_refs.extend(deepcopy(page.items[0].meaning_refs))
    page.items[1].fact_ids.extend(page.items[0].fact_ids)
    merged = inline_group(page)
    assert len(merged.items[0].meaning_refs) == 3
    assert len(merged.items[0].fact_ids) == 3
    page.items[0].text = 'X' * 6000
    assert inline_group(page) is None


def test_selection_uses_gateway_and_records_operation_in_local_only_mode():
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
    from adaptive_document_agent.services.llm.config import PrivacyMode
    review, catalog, draft = fixture()
    choices = layout_choices(draft, catalog, review, expand_compact)
    from adaptive_document_agent.agent.summary_layout_feedback import layout_feedback
    record = dict(layout_feedback=layout_feedback(draft, None, review, catalog))
    client = MockLLMClient([{key: 'inline' for key in choices}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, privacy_mode=PrivacyMode.LOCAL_ONLY))
    revised = choose_layout(gateway, draft, catalog, review, record, choices, CompactSummaryDraft)
    assert revised and len(client.calls) == 1
    assert gateway.usage[0]['operation'] == 'SummaryLayoutChoice'


def test_choice_success_still_enters_fresh_independent_meaning_review(monkeypatch):
    from adaptive_document_agent.agent import compact_summary
    from adaptive_document_agent.models.presentation import CompanyProfile
    from tests.test_compact_summary_v111 import fixture as source_fixture
    result, _, _ = source_fixture(3)
    review, catalog, draft = fixture()
    client = Client(draft)
    monkeypatch.setattr(compact_summary, 'author_draft', lambda *args, **kwargs: draft)
    def independent_review(*args, **kwargs):
        raise RuntimeError('independent reviewer reached')
    monkeypatch.setattr(compact_summary, 'review_compact', independent_review)
    with pytest.raises(RuntimeError, match='independent reviewer reached'):
        compact_summary.generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert review.plan_audits[-1]['fresh_complete_meaning_review'] is True
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutChoice']
    assert review.status == 'incomplete'


def test_native_generation_keeps_exact_combined_copy_and_measured_page_count():
    from pptx import Presentation
    from adaptive_document_agent.models.summary_display import SummaryDisplay
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    from adaptive_document_agent.services.presentation_brief import BriefItem, render_profile
    review, catalog, draft = fixture()
    revised, pages = paginate_draft(Client(draft), draft, catalog, review, [], {},
        expand_compact, CompactSummaryDraft)
    deck, rendered = Presentation(_resolve_template_path()), []
    for page in pages:
        rendered.extend(render_profile(deck, page.title, [BriefItem(item.label, item.text,
            item.source_pages, display=item.display or SummaryDisplay()) for item in page.items]))
    assert len(rendered) == len(pages) == review.max_intro_slides
    visible = ''.join(shape.text for slide in rendered for shape in slide.shapes
                      if shape.name == 'brief:body')
    assert visible == revised.pages[0].items[0].text
