"""Cross-language quotations cannot turn present visible content into an omission."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.compact_summary import SummaryCoverageReview
from adaptive_document_agent.agent.compact_summary_review import (
    CompactReviewProtocolError, review_compact, validate_review_target,
)
from adaptive_document_agent.agent.prompting import untrusted_document_message
from adaptive_document_agent.agent.summary_coverage import validate_coverage_target
from adaptive_document_agent.services.introduction_audience import coverage_errors
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName
from adaptive_document_agent.services.visible_summary_paragraphs import visible_paragraphs


SOURCE = 'Delivery requires staff training and customer acceptance.'
VISIBLE = '服务交付须完成员工培训并获得客户验收。'


def setup(responses, *, texts=(VISIBLE,), owners=None):
    pages = [SimpleNamespace(id='visible-1', items=[SimpleNamespace(text=text,
        part_ids=(owners or [['source-part']] * len(texts))[i]) for i, text in enumerate(texts)])]
    meanings = [dict(meaning=SOURCE, source_quote=SOURCE)]
    review = SimpleNamespace(audience_selection={'decisions': [
        dict(part_id='source-part', include=True, required_meanings=meanings)]})
    messages = [{'role': 'system', 'content': 'Independently review the current visible copy.'},
        untrusted_document_message(json.dumps({'source': {'parts': [dict(id='source-part', required_meanings=meanings)]},
            'pages': [{'id': 'visible-1', 'items': [dict(text=i.text, part_ids=i.part_ids) for i in pages[0].items]}]}))]
    client = MockLLMClient(responses)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.OLLAMA, model='fixture', privacy_mode=PrivacyMode.LOCAL_ONLY))
    audit = {}
    def validate(response):
        validate_review_target(response, pages, {'source-part'}, False)
        validate_coverage_target(response, review, pages)
    def run():
        return review_compact(gateway, messages, SummaryCoverageReview, audit,
                              validate=validate, coverage_pages=pages)
    return run, audit, client, pages, meanings, messages


def verdict(*, covered=True, quote='', ids=()):
    return dict(parts=[dict(part_id='source-part', accepted=covered, reason='Independent meaning judgment.',
        coverage=[dict(meaning_index=0, covered=covered, summary_quote=quote, paragraph_ids=list(ids),
                       reason='The current copy preserves the conditions.' if covered else 'Training is absent.')])],
        opening_accepted=True, opening_reason='The current opening explains the actual service.')


def test_source_quote_then_false_omission_gets_one_independent_visible_copy_recheck():
    run, audit, client, pages, meanings, messages = setup([
        verdict(quote=SOURCE), verdict(covered=False), verdict(ids=['v0_i0'])])
    original_messages = deepcopy(messages)
    response = run()
    assert response.parts[0].accepted and response.parts[0].coverage[0].summary_quote == VISIBLE
    assert not coverage_errors(response.parts[0].model_dump(), meanings, pages)
    assert [a['status'] for a in audit['compact_review_attempts']] == [
        'invalid_target', 'quote_verdict_disagreement', 'success']
    assert len(client.calls) == 3 and messages == original_messages
    assert 'conflicting reviews' in client.calls[2][-1]['content']
    supplied = json.loads(client.calls[0][1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert supplied['bound_visible_paragraphs']['source-part'] == [dict(paragraph_id='v0_i0', text=VISIBLE)]


def test_recheck_can_confirm_a_real_omission_without_silently_accepting_it():
    run, audit, client, pages, meanings, _ = setup([
        verdict(quote=SOURCE), verdict(covered=False), verdict(covered=False)], texts=('服务已投入运营。',))
    response = run()
    assert not response.parts[0].accepted and coverage_errors(response.parts[0].model_dump(), meanings, pages)
    assert len(client.calls) == 3


def test_real_rejection_without_a_prior_quote_error_does_not_trigger_extra_reviews():
    run, audit, client, *_ = setup([verdict(covered=False)])
    assert not run().parts[0].accepted and len(client.calls) == 1


@pytest.mark.parametrize('ids', [['unknown'], ['v0_i0', 'v0_i0'], ['v0_i1']])
def test_unknown_duplicate_and_other_part_addresses_fail_closed(ids):
    run, audit, client, *_ = setup([verdict(ids=ids), verdict(ids=ids)],
        texts=(VISIBLE, '其他事项。'), owners=[['source-part'], ['other-part']])
    with pytest.raises(CompactReviewProtocolError): run()
    assert len(client.calls) == 2


def test_noncontiguous_paragraphs_keep_exact_own_text_and_revalidate_later():
    run, audit, client, pages, meanings, _ = setup([verdict(ids=['v0_i0', 'v0_i2'])],
        texts=('服务交付须完成员工培训。', '无关段落。', '服务交付亦须获得客户验收。'))
    response = run()
    data = response.parts[0].model_dump()
    assert not coverage_errors(data, meanings, pages)
    pages[0].items[2].text = '服务交付无需客户验收。'
    assert coverage_errors(data, meanings, pages)
    assert audit['compact_review_attempts'][0]['visible_paragraph_binding']['semantic_approval'] is False


def test_exact_continuations_form_one_visible_paragraph_without_borrowing_other_copy():
    pages = [SimpleNamespace(items=[SimpleNamespace(text='Lightweight and com', part_ids=['p'],
                continuation_group='g', continuation_index=0)]),
             SimpleNamespace(items=[SimpleNamespace(text='pact.', part_ids=['p'],
                continuation_group='g', continuation_index=1)])]
    assert visible_paragraphs(pages) == {'v0_i0': dict(paragraph_id='v0_i0', part_ids=['p'], text='Lightweight and compact.')}
    pages[1].items[0].part_ids = ['another-part']
    assert visible_paragraphs(pages)['v0_i0']['part_ids'] == []


def test_second_invalid_protocol_response_still_stops_at_two_calls():
    run, audit, client, *_ = setup([verdict(quote=SOURCE), verdict(quote=SOURCE), verdict(ids=['v0_i0'])])
    with pytest.raises(CompactReviewProtocolError): run()
    assert len(client.calls) == 2


def test_missing_source_binding_does_not_receive_a_quote_disagreement_retry():
    run, audit, client, *_ = setup([verdict(quote=SOURCE), verdict(covered=False)], owners=[['other-part']])
    assert not run().parts[0].accepted and len(client.calls) == 2


def test_invalid_disagreement_response_has_no_fourth_request():
    run, audit, client, *_ = setup([verdict(quote=SOURCE), verdict(covered=False),
                                  '{invalid', verdict(ids=['v0_i0'])])
    with pytest.raises(CompactReviewProtocolError): run()
    assert len(client.calls) == 3
