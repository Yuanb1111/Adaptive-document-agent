import json

import pytest

from adaptive_document_agent.agent.brief_audit_scope import audit_status_errors
from adaptive_document_agent.agent.brief_header_repair import repair_brief_headers
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.models.executive_brief import BRIEF_EVIDENCE_LIMIT
from adaptive_document_agent.agent.topic_evidence_review import (
    CoverageTopicReviewError, review_covered_topics, unreviewed_topics,
)
from tests.test_brief_audit_scope_v146 import _case
from tests.test_topic_evidence_binding_v201 import decision, gateway, setup


@pytest.mark.parametrize('outcome', ['accepted', 'rebound', 'omitted', 'unsupported'])
def test_final_review_can_correct_wording_only_on_the_covered_series(outcome):
    result, lookup, annual, adverse, selection = setup()
    source = selection.topics[0]
    sibling = source.model_copy(update={'id': 'unchanged', 'series_ids': [annual]})
    selection.topics.append(sibling)
    revised = source.model_copy(update={'title': 'Waste', 'question': 'How did waste change?',
                                        'series_ids': [annual if outcome == 'rebound' else adverse]})
    responses = [
        {'decisions': [decision(source.id, False), decision(sibling.id)]},
        {'topics': [] if outcome == 'omitted' else [revised.model_dump()]},
        {'decisions': [decision(source.id, outcome != 'unsupported')]},
    ]
    gw, client = gateway(responses)

    def run():
        return review_covered_topics(selection, lookup, result, gw, PresentationTopicSelector._validate)

    if outcome == 'accepted':
        final = run()
        assert final.topics == [revised, sibling] and not unreviewed_topics(final, lookup, result)
        assert final.omissions == selection.omissions
        assert source.title == 'Output'
    else:
        with pytest.raises(CoverageTopicReviewError, match='activity'):
            run()
    assert len(client.calls) == (2 if outcome in {'rebound', 'omitted'} else 3)
    payload = json.loads(client.calls[1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert [t['id'] for t in payload['topics']] == [source.id]
    assert payload['rejection'] == decision(source.id, False)
    assert [s['series_id'] for s in payload['series']] == [adverse]
    assert 'source_pages' in payload
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['accepted_bindings']  # Even a failed correction retains its approved sibling.


def _header_case():
    result, brief = _case()
    item = brief.items[0]
    page = result.document.pages[0]
    quotes = ['Programme fees . . . 1,250 1,475', 'A statement of scope.',
              'A separate historical passage.', 'Additional source discussion.']
    quotes.extend(f'Additional context passage {i}.' for i in range(BRIEF_EVIDENCE_LIMIT - len(quotes)))
    page.text += '\n' + '\n'.join(quotes[1:])
    item.evidence = [item.evidence[0].model_copy(update={'text': q}) for q in quotes]
    item.text = 'Programme fees were USD1,250 thousand in unaudited 6M2023.'
    return result, brief, {page.page_number: page.text}


def test_retry_does_not_reuse_an_invalid_coverage_wording_change(tmp_path):
    from adaptive_document_agent.utils.caching import DiskCache
    result, lookup, annual, _, selection = setup()
    changed_scope = selection.model_copy(deep=True)
    changed_scope.topics[0].series_ids = [annual]
    gw, client = gateway([{'decisions': [decision('activity', False)]}, changed_scope.model_dump(),
                          {'decisions': [decision('activity')]}])
    gw.cache = DiskCache(tmp_path)
    with pytest.raises(CoverageTopicReviewError):
        review_covered_topics(selection, lookup, result, gw, PresentationTopicSelector._validate)
    assert not list(tmp_path.glob('llm-*.json'))
    actual = review_covered_topics(selection, lookup, result, gw, PresentationTopicSelector._validate)
    assert actual == selection and len(client.calls) == 3


@pytest.mark.parametrize('choice', [0, None, 99])
def test_header_choice_keeps_page_rows_and_quote_limit(choice):
    result, brief, excerpts = _header_case()
    item = brief.items[0]
    before = brief.model_dump()
    assert audit_status_errors(item, result)
    gw, client = gateway([{'choices': {'0': choice}}])
    audit = {}
    updated = repair_brief_headers(gw, brief, [0], result, excerpts, audit)
    assert bool(audit_status_errors(updated.items[0], result)) == (choice != 0)
    assert len(updated.items[0].evidence) == BRIEF_EVIDENCE_LIMIT
    assert updated.items[0].evidence[0] == item.evidence[0]
    assert updated.items[0].text == item.text
    if choice == 99:
        assert 'offered evidence' in audit['header_evidence_repair']['error']
    assert len(client.calls) == 1 and brief.model_dump() == before
    options = audit['header_evidence_repair']['options']['0']
    assert all(o['replace_quote'] > 0 and o['header']['text'] in excerpts[1] for o in options)


def test_header_repair_cannot_guess_geometry_or_revise_a_locked_item():
    result, brief, excerpts = _header_case()
    gw, client = gateway([])
    assert repair_brief_headers(gw, brief, [], result, excerpts, {}) is brief
    result.document.pages[0].text_blocks = []
    assert repair_brief_headers(gw, brief, [0], result, excerpts, {}) is brief
    assert not client.calls


@pytest.mark.parametrize('accept_bound_claim', [True, False])
def test_brief_patch_reviews_the_changed_citations_before_acceptance(accept_bound_claim):
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    result, brief, excerpts = _header_case()
    gw, _ = gateway([brief.model_dump(), {'item_0': brief.items[0].model_dump()}, {'choices': {'0': 0}}])
    bound_reviews = []

    def independent(candidate):
        errors = audit_status_errors(candidate.items[0], result)
        if not errors:
            bound_reviews.append(candidate.model_copy(deep=True))
            if not accept_bound_claim:
                errors.append('The revised evidence still omits a qualification')
        return {0: errors} if errors else {}

    def run():
        return generate_with_item_repair(gw, [dict(role='system', content='Review sources.')],
            result=result, excerpts=excerpts, topics=[], source_context={}, semantic_validator=independent)

    if accept_bound_claim:
        assert run() == bound_reviews[-1]
    else:
        with pytest.raises(ValueError, match='qualification'):
            run()
    assert bound_reviews and brief.items[0].evidence != bound_reviews[-1].items[0].evidence


def test_failed_final_topic_review_stops_reporting_before_briefing(monkeypatch):
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
    from tests.test_reporting_checkpoint_v144 import SyntheticCoverageFlowClient, _coverage_fixture
    source, raw = _coverage_fixture()
    client = SyntheticCoverageFlowClient(source)
    gw = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model='offline',
                                        presentation_strategy='full_catalog'))
    runner = DocumentOrchestrator(gw)
    monkeypatch.setattr(runner, '_load_document', lambda *args: source.document)

    def rejected(*args):
        raise CoverageTopicReviewError('Application units do not match the cited source')

    monkeypatch.setattr(PresentationTopicSelector, 'select', rejected)
    result = runner.analyse_pdf(raw, resume=source)
    assert (result.pipeline_state, result.failed_stage, result.retry_from) == (
        'partial', 'presentation_coverage', 'reporting')
    assert 'Application units' in result.failure_details['message']
    assert result.analysis_results == source.analysis_results
    assert 'ExecutiveBrief' not in client.calls
