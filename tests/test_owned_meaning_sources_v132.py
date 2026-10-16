"""Canonical evidence is copied from the owner; unsupported assertions still fail review."""
from tests.introduction_review_helpers import review_response
import json
import pytest
from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.agent.compact_summary import compact_input
from adaptive_document_agent.services.introduction_audience import audience_part_ids
from tests.test_compact_summary_v111 import fixture


class Client:
    def __init__(self, *, accept=True):
        self.accept = accept
        self.reviews = []

    def generate_structured(self, messages, schema, **kwargs):
        if schema.__name__ == 'IntroductionAudienceSelection':
            return schema(decisions=[dict(part_id='part-0', include=True, reason='The core service condition is essential.',
                required_meanings=[dict(meaning='The scheduling service requires staff training before delivery.'
                    if self.accept else 'The scheduling service has no staff training requirement.',
                    source_quote='A model reconstruction that is not actual source text.')])])
        payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        self.reviews.append(payload)
        return review_response(schema, messages, accepted=self.accept, reason='The source requires staff training before service delivery.')


def test_exact_owner_source_replaces_model_retyping_before_independent_review():
    result, review, _ = fixture(1)
    original = review.parts[0].source_text
    client = Client()
    select_introduction_audience(client, result, review)
    meaning = client.reviews[0]['decisions'][0]['required_meanings'][0]
    assert 'source_quote' not in meaning
    assert client.reviews[0]['source']['parts'][0]['source_text'] == original
    assert review.audience_selection['decisions'][0]['required_meanings'][0]['source_quote'] == original
    assert meaning['proposed_source_quote'] == 'A model reconstruction that is not actual source text.'
    assert audience_part_ids(review) == {'part-0'}
    payload, _ = compact_input(review)
    assert payload['parts'][0]['required_meanings'][0]['source_quote'] == original
    assert 'proposed_source_quote' not in payload['parts'][0]['required_meanings'][0]


def test_review_does_not_apply_author_empty_quote_instruction_to_python_bound_evidence():
    from adaptive_document_agent.agent.introduction_audience import _AUTHOR_EVIDENCE_RULE
    result, review, _ = fixture(1)
    class CheckRoles(Client):
        def generate_structured(self, messages, schema, **kwargs):
            system = messages[0]['content']
            if schema.__name__ == 'IntroductionAudienceSelection':
                assert _AUTHOR_EVIDENCE_RULE in system
            else:
                assert _AUTHOR_EVIDENCE_RULE not in system
                assert 'leave source_quote empty' not in system
                assert 'source.parts[].source_text by part_id' in system
                assert 'reject a meaning not grounded in that exact part' in system
            return super().generate_structured(messages, schema, **kwargs)
    select_introduction_audience(CheckRoles(), result, review)
    assert review.audience_selection['independent_review']['accepted']
    assert review.audience_selection['decisions'][0]['required_meanings'][0]['source_quote'] == review.parts[0].source_text


def test_copying_owned_evidence_cannot_certify_an_unsupported_assertion():
    result, review, _ = fixture(1)
    client = Client(accept=False)
    with pytest.raises(ValueError, match='not independently accepted'):
        select_introduction_audience(client, result, review)
    assert len(client.reviews) == 2
    assert review.audience_part_ids is None and not review.audience_selection
    assert all('source_quote' not in p['decisions'][0]['required_meanings'][0]
               and p['source']['parts'][0]['source_text'] == review.parts[0].source_text
               for p in client.reviews)
    history = [a for a in review.plan_audits if 'introduction_audience_attempt' in a]
    assert len(history) == len(client.reviews)
    assert all(a['decisions'][0]['required_meanings'][0]['source_quote'] == review.parts[0].source_text
               for a in history)


def test_post_review_quote_changes_fail_even_if_they_are_owned_substrings():
    result, review, _ = fixture(1)
    select_introduction_audience(Client(), result, review)
    review.audience_selection['decisions'][0]['required_meanings'][0]['source_quote'] = 'requires staff training before service delivery.'
    with pytest.raises(ValueError, match='complete current source'):
        audience_part_ids(review)
