"""Exact meaning progress and a single independent late-omission authorization."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, generate_compact_summary
from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage
from tests.introduction_review_helpers import review_response
from tests.test_compact_summary_v111 import fixture


MEANINGS = ['The scheduling service is modular and supports coordinated planning across registered operating teams.', 'Installation requires trained staff.',
            'Capacity is limited during inspections.', 'Operation is limited to indoor sites.']


def source_fixture():
    result, reading, _ = fixture(1)
    source = ' '.join(MEANINGS) + '\n'
    reading.parts[0].source_text = source
    reading.parts[0].facts[0].text = reading.parts[0].facts[0].source_quote = source.strip()
    reading.source_blocks[0].text = result.document.pages[0].text = source
    reading.source_blocks[0].char_end = len(source)

    class Audience:
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'IntroductionAudienceSelection':
                return schema(decisions=[dict(part_id='part-0', include=True,
                    reason='The service definition and operating prerequisites are essential.',
                    required_meanings=[dict(meaning=value) for value in MEANINGS])])
            return review_response(schema, messages, accepted=True,
                reason='The selected service definition and qualifications are source supported.')

    select_introduction_audience(Audience(), result, reading)
    return result, reading


def payload_from(messages):
    for message in reversed(messages):
        try:
            value = json.loads(message['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        except (ValueError, IndexError):
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError('Missing structured test payload')


def item(text, indices=range(4)):
    return dict(label='Service conditions', text=text, fact_ids=['f0'],
        meaning_refs=[dict(part_id='part-0', meaning_index=index, summary_quote=text) for index in indices])


class LateClient:
    def __init__(self, fault=None):
        self.fault = fault
        self.calls, self.review_payloads, self.progress_requests = [], [], []
        self.revisions = 0
        self.first = MEANINGS[0] + ' Installation requires staff.'
        self.second = ' '.join(MEANINGS[:2])
        self.third = self.second + ' Capacity is limited during inspections.'

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if issubclass(schema, CompactSummaryDraft):
            text = '\n'.join(m['content'] for m in messages)
            assert 'stay within 350 English words' not in text
            assert 'Financial or market numbers are optional' not in text
            assert 'Every independently selected required_meanings entry is mandatory' in text
            assert 'meaning_inventory' in text
            return schema(pages=[dict(title='Service and operating conditions', items=[item(self.first)])])
        payload = payload_from(messages)
        if schema.__name__ == 'SummarySynthesisRevision':
            self.revisions += 1
            target_indices = {d['meaning_index'] for d in payload['meaning_deficits']}
            if self.revisions < 3:
                assert target_indices == ({1, 2} if self.revisions == 1 else {2})
                return schema(replacements=[dict(item_id='g0_i0', replacement=item(
                    self.second if self.revisions == 1 else self.third))])
            assert target_indices == {3}
            assert schema.model_fields['replacements'].metadata[-1].max_length == 0
            addition = item(MEANINGS[3], [3])
            if self.fault == 'late_source': addition['fact_ids'] = ['unknown']
            return schema(additions=[dict(group_id='g0', item=addition)])
        if schema.__name__ == 'SummaryLateOmissionReview':
            self.progress_requests.append((deepcopy(messages), deepcopy(kwargs)))
            assert payload['previous_deficits'] == [dict(part_id='part-0', meaning_index=i) for i in (1, 2)]
            assert payload['current_deficits'] == [dict(part_id='part-0', meaning_index=3)]
            if self.fault in ('length_once', 'length_always') and (
                    self.fault == 'length_always' or len(self.progress_requests) == 1):
                raise LLMStructuredOutputError('Output limit', response=LLMResponse(text='{"previous_deficits":',
                    usage=LLMUsage(provider='mock', model='mock', finish_reason='length')))
            if self.fault == 'api_error':
                raise LLMResponseError('Unavailable semantic progress response')
            previous = [dict(part_id='part-0', meaning_index=index, resolved=True,
                summary_quote=MEANINGS[index], reason='Current owned copy explicitly states this condition.') for index in (1, 2)]
            current = [dict(part_id='part-0', meaning_index=3,
                missing_only=self.fault != 'unsupported', reason='Indoor-site scope is missing from the current copy.')]
            if self.fault == 'duplicate': previous[1]['meaning_index'] = 1
            elif self.fault == 'unknown': current[0]['meaning_index'] = 99
            elif self.fault == 'missing': previous.pop()
            elif self.fault == 'wrong_quote': previous[0]['summary_quote'] = 'A qualification absent from current copy.'
            elif self.fault == 'unresolved': previous[0]['resolved'] = False
            return schema(previous_deficits=previous, current_deficits=current)
        assert schema.__name__ == 'SummaryCoverageReview'
        self.review_payloads.append(deepcopy(payload))
        round_number = len(self.review_payloads)
        assert len(payload['source']['parts']) == 1
        assert len(payload['source']['parts'][0]['required_meanings']) == 4
        failures = [{1, 2}, {2}, {3}, set()][round_number - 1]
        if self.fault == 'no_progress' and round_number == 2: failures = {1, 2}
        if self.fault == 'old_deficit' and round_number == 3: failures = {2, 3}
        if self.fault == 'final_missing' and round_number == 4: failures = {3}
        if self.fault == 'another_new' and round_number == 4: failures = {0}
        visible = ' '.join(i['text'] for p in payload['pages'] for i in p['items'])
        checks = [dict(meaning_index=index, covered=index not in failures,
            summary_quote=visible if index not in failures else '',
            reason='Explicit source qualification is missing.' if index in failures else 'Current owned copy preserves this meaning.')
            for index in range(4)]
        return schema(parts=[dict(part_id='part-0', accepted=not failures,
            reason='Every required condition must be visible.', coverage=checks)],
            opening_accepted=not (self.fault == 'opening' and round_number == 3),
            opening_reason='The current opening must explain the actual service.',
            opening_slide_id=payload['opening_target']['slide_id'],
            opening_item_texts=payload['opening_target']['item_texts'])


def run(client):
    result, reading = source_fixture()
    company = CompanyProfile(summary_review=reading)
    return result, reading, company, lambda: generate_compact_summary(client, result, reading, company)


@pytest.mark.parametrize('fault', [None, 'length_once'])
def test_exact_same_part_progress_then_late_new_omission_gets_one_additive_correction(fault):
    client = LateClient(fault)
    _, reading, company, generate = run(client)
    generate()
    assert client.revisions == 3 and len(client.review_payloads) == 4
    assert client.calls.count('SummaryLateOmissionReview') == (2 if fault else 1)
    assert [i.text for p in company.summary_pages for i in p.items] == [client.third, MEANINGS[3]]
    audits = [a for a in reading.plan_audits if 'compact_attempt' in a]
    assert len(audits) == 4
    assert all(a['fresh_complete_meaning_review'] and not a['retained_part_reviews'] for a in audits)
    assert all(a['authored_meaning_coverage']['structurally_complete'] for a in audits)
    assert all(a['authored_meaning_coverage']['semantic_approval'] is False for a in audits)
    assert audits[1]['meaning_deficit_progress']['previous_resolved'] == [dict(part_id='part-0', meaning_index=1)]
    assert audits[2]['late_omission_review']['authorized'] is True
    assert audits[3]['content_revision_policy'] == 'additive_meaning_regression'
    if fault:
        assert [kw['max_tokens'] for _, kw in client.progress_requests] == [32000, 40000]
        assert client.progress_requests[0][0] == client.progress_requests[1][0]
        assert all(kw['allow_repair'] is False for _, kw in client.progress_requests)


@pytest.mark.parametrize('fault', ['unsupported', 'duplicate', 'unknown', 'missing', 'wrong_quote', 'unresolved'])
def test_late_authorization_never_accepts_unresolved_or_unbound_semantics(fault):
    client = LateClient(fault)
    _, reading, company, generate = run(client)
    with pytest.raises(ValueError, match='theme unavailable'):
        generate()
    assert client.revisions == 2 and len(client.review_payloads) == 3
    assert len(client.progress_requests) == 1
    assert not company.summary_pages
    record = next(a['late_omission_review'] for a in reading.plan_audits if 'late_omission_review' in a)
    assert record['authorized'] is False


@pytest.mark.parametrize('fault,expected_reviews', [('no_progress', 2), ('old_deficit', 3), ('opening', 3)])
def test_repeated_deficits_or_opening_failure_cannot_spend_the_late_budget(fault, expected_reviews):
    client = LateClient(fault)
    _, _, company, generate = run(client)
    with pytest.raises(ValueError, match='theme unavailable'):
        generate()
    assert len(client.review_payloads) == expected_reviews
    assert not client.progress_requests and not company.summary_pages


@pytest.mark.parametrize('fault', ['final_missing', 'another_new'])
def test_final_rejection_is_not_locked_out_by_previous_acceptance_and_never_retries(fault):
    client = LateClient(fault)
    _, reading, company, generate = run(client)
    with pytest.raises(ValueError, match='theme unavailable'):
        generate()
    assert len(client.review_payloads) == 4 and client.revisions == 3
    assert len(client.progress_requests) == 1 and not company.summary_pages
    assert [a for a in reading.plan_audits if 'compact_attempt' in a][-1]['compact_semantic_review']['parts'][0]['accepted'] is False


@pytest.mark.parametrize('fault', ['length_always', 'api_error'])
def test_progress_transport_failure_is_audited_without_an_extra_semantic_attempt(fault):
    client = LateClient(fault)
    _, reading, company, generate = run(client)
    with pytest.raises(LLMResponseError):
        generate()
    assert client.revisions == 2 and not company.summary_pages
    assert len(client.progress_requests) == (2 if fault == 'length_always' else 1)
    record = next(a['late_omission_review'] for a in reading.plan_audits if 'late_omission_review' in a)
    assert record['status'] == 'failed' and record['authorized'] is False


@pytest.mark.parametrize('fault', ['late_source', 'late_overflow'])
def test_late_addition_cannot_escape_protected_copy_through_layout_or_source_rewrites(fault, monkeypatch):
    if fault == 'late_overflow':
        from adaptive_document_agent.agent import summary_layout_repair
        original = summary_layout_repair.pack_theme_pages
        def overflow_after_addition(pages):
            packed = original(pages)
            return packed * 6 if sum(len(page.items) for page in pages) > 1 else packed
        monkeypatch.setattr(summary_layout_repair, 'pack_theme_pages', overflow_after_addition)
    client = LateClient(fault)
    _, reading, company, generate = run(client)
    with pytest.raises(ValueError, match='physical layout|unknown or repeated fact IDs'):
        generate()
    assert client.calls.count('CompactSummaryDraft') == 1
    assert client.revisions == 3 and len(client.review_payloads) == 3
    assert not company.summary_pages
    assert [a for a in reading.plan_audits if 'compact_attempt' in a][-1]['strict_additive_candidate']
