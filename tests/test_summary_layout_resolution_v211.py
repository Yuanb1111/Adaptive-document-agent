"""A rejected measured option can use the same final correction to regroup."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, expand_compact
from adaptive_document_agent.agent.summary_layout_choices import inline_group
from adaptive_document_agent.agent.summary_layout_feedback import compression_binding_errors
from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
from adaptive_document_agent.agent.summary_draft_protocol import SummaryDraftProtocolError
from adaptive_document_agent.agent.summary_writer_copy import address_only_copy
from tests.test_summary_layout_choices_v191 import fixture, Client


class ReplacementClient(Client):
    def __init__(self, draft, replacement, choice='keep'):
        super().__init__(draft, choice)
        self.replacement = replacement

    def generate_structured(self, messages, schema, **kwargs):
        if schema.__name__ != 'SummaryLayoutChoice':
            return super().generate_structured(messages, schema, **kwargs)
        self.operations.append(schema.__name__)
        self.calls.append(deepcopy(messages))
        assert kwargs['allow_repair'] is False
        response = {key: self.choice for key in schema.model_fields if key != 'replacement'}
        response['replacement'] = address_only_copy(self.replacement)
        return schema.model_validate(response)


def replacement_fixture():
    review, catalog, draft = fixture()
    replacement = dict(pages=[inline_group(draft.pages[0]).model_dump(mode='json')])
    replacement['pages'][0]['items'][0]['label'] = 'Combined service scope'
    return review, catalog, draft, replacement


def run(client, draft, catalog, review, audit):
    return paginate_draft(client, draft, catalog, review, [], audit,
                          expand_compact, CompactSummaryDraft)


def test_semantic_refusal_can_regroup_within_the_same_two_call_budget():
    review, catalog, draft, replacement = replacement_fixture()
    snapshot, audit = draft.model_dump(), {}
    client = ReplacementClient(draft, replacement)
    revised, pages = run(client, draft, catalog, review, audit)
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutChoice']
    assert len(pages) == review.max_intro_slides == 2
    assert [row['status'] for row in audit['layout_attempts']] == ['overflow', 'overflow', 'success']
    assert draft.model_dump() == snapshot
    assert not compression_binding_errors(revised, draft, catalog)
    assert revised.model_dump(exclude={'pages'}) == draft.model_dump(exclude={'pages'})
    item = revised.pages[0].items[0]
    assert all(ref.summary_quote == item.text for ref in item.meaning_refs)
    choice = audit['layout_attempts'][1]['lossless_layout_choice']
    assert choice['mode'] == 'replacement' and choice['writer_reference_count'] == 3
    assert choice['semantic_approval'] is choice['additional_rewrite_round'] is False
    assert review.status == 'incomplete'
    messages = client.calls[-1]
    assert 'THIS SAME response' in messages[0]['content']
    assert 'independent source and meaning review' in messages[0]['content']
    assert 'untrusted DATA' in messages[0]['content']
    assert 'layout_feedback' in messages[1]['content']
    assert 'source_quotes' in messages[1]['content']
    assert 'alternatives' in messages[2]['content']
    assert 'FINAL bounded' in messages[-1]['content']


@pytest.mark.parametrize('mutation', ['missing_meaning', 'unknown_fact', 'removed_fact',
                                    'wrong_owner', 'still_over_budget'])
def test_replacement_must_pass_existing_source_and_geometry_guards(mutation):
    review, catalog, draft, replacement = replacement_fixture()
    item = replacement['pages'][0]['items'][0]
    if mutation == 'missing_meaning':
        item['meaning_refs'].pop()
    elif mutation == 'unknown_fact':
        item['fact_ids'].append('unknown')
    elif mutation == 'removed_fact':
        item['fact_ids'].pop()
    elif mutation == 'wrong_owner':
        item['meaning_refs'][0]['part_id'] = 'unowned'
    else:
        replacement['pages'] = draft.model_dump(mode='json')['pages']
    client, audit = ReplacementClient(draft, replacement), {}
    with pytest.raises(SummaryDraftProtocolError, match='source preservation|layout repair exhausted'):
        run(client, draft, catalog, review, audit)
    assert len(client.calls) == 2
    assert review.max_intro_slides == 2 and review.status == 'incomplete'
    assert len(audit['layout_attempts']) == 3


@pytest.mark.parametrize('mutation', ['identity', 'mixed_patch'])
def test_ambiguous_or_identity_editing_responses_are_rejected(mutation):
    review, catalog, draft, replacement = replacement_fixture()
    if mutation == 'identity':
        replacement['name'] = 'Changed identity'
    client = ReplacementClient(draft, replacement, 'inline' if mutation == 'mixed_patch' else 'keep')
    audit = {}
    with pytest.raises(ValueError):
        run(client, draft, catalog, review, audit)
    assert audit['layout_attempts'][1]['lossless_layout_choice']['status'] == 'failed'
    assert len(client.calls) == 2


def test_replacement_success_still_requires_fresh_independent_review(monkeypatch):
    from adaptive_document_agent.agent import compact_summary
    from adaptive_document_agent.models.presentation import CompanyProfile
    from tests.test_compact_summary_v111 import fixture as source_fixture
    result, _, _ = source_fixture(3)
    review, _, draft, replacement = replacement_fixture()
    client = ReplacementClient(draft, replacement)
    monkeypatch.setattr(compact_summary, 'author_draft', lambda *args, **kwargs: draft)
    def independent_review(*args, **kwargs):
        raise RuntimeError('independent reviewer reached')
    monkeypatch.setattr(compact_summary, 'review_compact', independent_review)
    with pytest.raises(RuntimeError, match='independent reviewer reached'):
        compact_summary.generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert review.plan_audits[-1]['fresh_complete_meaning_review'] is True
    assert review.status == 'incomplete'


def test_replacement_uses_gateway_in_local_only_and_matches_native_rendering():
    from pptx import Presentation
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
    from adaptive_document_agent.services.llm.config import PrivacyMode
    from adaptive_document_agent.agent.summary_layout_choices import layout_choices, choose_layout
    from adaptive_document_agent.agent.summary_layout_feedback import layout_feedback
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    from adaptive_document_agent.services.presentation_brief import BriefItem, render_profile
    review, catalog, draft, replacement = replacement_fixture()
    choices = layout_choices(draft, catalog, review, expand_compact)
    response = {key: 'keep' for key in choices}
    response['replacement'] = address_only_copy(replacement)
    provider = MockLLMClient([response])
    gateway = LLMGateway(provider, LLMSettings(provider=ProviderName.MOCK, privacy_mode=PrivacyMode.LOCAL_ONLY))
    revised = choose_layout(gateway, draft, catalog, review,
        dict(layout_feedback=layout_feedback(draft, None, review, catalog)), choices, CompactSummaryDraft)
    _, pages = paginate_draft(gateway, revised, catalog, review, [], {}, expand_compact,
                             CompactSummaryDraft, allow_rewrite=False)
    assert len(provider.calls) == 1
    assert gateway.usage[0]['operation'] == 'SummaryLayoutChoice'
    deck, rendered = Presentation(_resolve_template_path()), []
    for page in pages:
        rendered.extend(render_profile(deck, page.title, [BriefItem(item.label, item.text, item.source_pages)
                                                       for item in page.items]))
    assert len(rendered) == len(pages) == review.max_intro_slides
    visible = ''.join(shape.text for slide in rendered for shape in slide.shapes if shape.name == 'brief:body')
    assert visible == revised.pages[0].items[0].text
