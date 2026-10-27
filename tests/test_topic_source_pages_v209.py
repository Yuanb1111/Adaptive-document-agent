"""A generic row needs its original header/definition, with context-bound approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.topic_evidence_review import (
    evidence_payload, topic_binding, review_topic_evidence, require_topic_evidence_review,
)
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.models.page import DocumentPage
from tests.test_topic_evidence_binding_v201 import setup, gateway, decision


def contextual_case():
    result, lookup, annual, _, selection = setup()
    selection.topics[0].series_ids = [annual]
    result.pipeline_version = 'current'
    page = DocumentPage(page_number=234,
        text='FULL HEADER: Output counts completed work only.\n  Exact source whitespace.\nFull page footer.')
    result.document.pages = [DocumentPage(page_number=1, text='Unrelated source.'), page]
    return result, lookup, selection, page


def test_complete_owned_page_reaches_independent_reviewer_and_raw_rows_are_unchanged():
    result, lookup, selection, page = contextual_case()
    before = deepcopy((result.document, result.observations))
    g, client = gateway([{'decisions': [decision('activity')]}])
    actual = review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    payload = json.loads(client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert payload['source_pages'] == [dict(page=234, text=page.text)]
    assert payload['topic_source_pages'] == {'activity': [234]}
    assert payload['unavailable_source_pages'] == []
    assert payload['series'] == evidence_payload(selection.topics, lookup)['series']
    require_topic_evidence_review(actual, lookup, result)
    assert (result.document, result.observations) == before


def test_changed_context_cannot_reuse_new_approval_or_fall_back_to_legacy_rows():
    result, lookup, selection, page = contextual_case()
    g, _ = gateway([{'decisions': [decision('activity')]}])
    review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate)
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_evidence_review',
        severity='info', stage='presentation', message=json.dumps(dict(
            accepted_bindings=[topic_binding(selection.topics[0], lookup)]))))
    require_topic_evidence_review(selection, lookup, result)
    result.document.pages[0].text += 'Unrelated page changed.'
    require_topic_evidence_review(selection, lookup, result)
    page.text += '\nA changed source qualification.'
    with pytest.raises(ValueError, match='semantic review'):
        require_topic_evidence_review(selection, lookup, result)


def test_unavailable_page_is_explicit_and_never_manufactured():
    result, lookup, selection, _ = contextual_case()
    result.document.pages.pop()
    payload = evidence_payload(selection.topics, lookup, result)
    assert payload['source_pages'] == []
    assert payload['unavailable_source_pages'] == [234]
    assert payload['topic_source_pages'] == {'activity': [234]}


def test_oversized_full_page_fails_without_truncating_or_calling_model():
    result, lookup, selection, page = contextual_case()
    page.text = 'Complete original page. ' * 9000
    before = deepcopy(result.document)
    g, client = gateway([])
    with pytest.raises(ValueError, match='no facts sampled'):
        review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate,
                              allow_correction=False)
    assert not client.calls and result.document == before


def test_context_is_evidence_only_and_a_negative_verdict_still_blocks_acceptance():
    result, lookup, selection, _ = contextual_case()
    g, client = gateway([{'decisions': [decision('activity', False)]}])
    with pytest.raises(ValueError, match='No topic passed'):
        review_topic_evidence(selection, lookup, result, g, PresentationTopicSelector._validate,
                              allow_correction=False)
    assert len(client.calls) == 1
    with pytest.raises(ValueError, match='semantic review'):
        require_topic_evidence_review(selection, lookup, result)
