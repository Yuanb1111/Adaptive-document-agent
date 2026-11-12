"""A citation-capacity correction preserves copy and cannot grant source approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_integration_review import (
    SourceIntegrationDraft, review_supplementary_sources, resolved_source_check_ids,
)
from adaptive_document_agent.agent.source_integration_quotes import (
    SourceQuoteCapacityError, SourceQuoteBindingError, bind_source_quotes)
from adaptive_document_agent.agent.source_quote_capacity import bind_with_capacity_repair
from tests.test_source_integration_v166 import fixture, Gateway


def overflowing():
    result, constraint = fixture()
    result.document.pages[11].text = '\n'.join([
        'An introductory source heading.', 'General contractual information.',
        'The following disclosure qualifies orders.', (constraint + ' ') * 45])
    draft = SourceIntegrationDraft(decisions=[dict(section_id='contracts', disposition='omit',
        reason='Synthetic disposition for reference transport.', brief_item_indexes=[],
        evidence=[dict(page=12, text=f'@lines[{n}]') for n in range(1, 5)])])
    return result, constraint, draft


@pytest.mark.parametrize('valid', [True, False])
def test_capacity_patch_changes_only_requested_references_once(valid):
    result, constraint, draft = overflowing()
    pages = {p.page_number: p.text for p in result.document.pages}
    before = draft.model_dump()
    with pytest.raises(SourceQuoteCapacityError):
        bind_source_quotes(draft, pages)

    class References:
        calls = []
        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(messages)
            payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert set(payload['objects_to_rebind']) == {'decisions_0_evidence'}
            chosen = next(k for k, v in payload['reference_options'].items() if constraint in v['text'])
            return schema(decisions_0_evidence=[chosen if valid else 'invented-option'])

    gateway, entry, budget = References(), {}, {}
    if valid:
        bound = bind_with_capacity_repair(gateway, draft, pages, entry, budget)
        assert constraint in bound.decisions[0].evidence[0].text
        assert len(bound.decisions[0].evidence[0].text) <= 1800
        assert bound.decisions[0].model_dump(exclude={'evidence'}) == draft.decisions[0].model_dump(exclude={'evidence'})
    else:
        with pytest.raises(ValueError):
            bind_with_capacity_repair(gateway, draft, pages, entry, budget)
    assert draft.model_dump() == before
    assert budget['quote_capacity'] == 1 and len(gateway.calls) == 1
    with pytest.raises(SourceQuoteCapacityError):
        bind_with_capacity_repair(gateway, draft, pages, {}, budget)
    assert len(gateway.calls) == 1


@pytest.mark.parametrize('accepted', [True, False])
@pytest.mark.parametrize('defect', ['capacity', 'nonliteral'])
def test_reference_repair_still_requires_independent_source_review(accepted, defect):
    result, constraint, draft = overflowing()
    if defect == 'nonliteral':
        values = draft.model_dump()
        values['decisions'][0]['evidence'] = [dict(page=12,
            text='An invented reconstruction across source table columns.')]
        draft = SourceIntegrationDraft.model_validate(values)
    original = result.executive_brief.model_copy(deep=True)
    source = deepcopy(result.document)

    class ReviewGateway(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            if issubclass(schema, SourceIntegrationDraft):
                self.calls.append((messages, schema))
                proposal = draft.model_copy(deep=True)
                proposal.decisions[0].disposition = 'covered'
                proposal.decisions[0].brief_item_indexes = [0]
                return proposal
            if schema.__name__ == 'SourceQuoteReferences':
                self.calls.append((messages, schema))
                payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                return schema(decisions_0_evidence=[next(k for k, v in payload['reference_options'].items()
                    if constraint in v['text'])])
            return super().generate_structured(messages, schema, **kwargs)

    gateway = ReviewGateway(constraint, accept=accepted)
    merged = review_supplementary_sources(gateway, result, original)
    assert bool(resolved_source_check_ids(result, merged)) is accepted
    assert merged == original and result.document == source
    assert [s.__name__ for _, s in gateway.calls][:3] == [
        'SourceIntegrationDraft', 'SourceQuoteReferences', 'SourceIntegrationReview']
    assert sum(s.__name__ == 'SourceQuoteReferences' for _, s in gateway.calls) == 1


def test_saved_capacity_failure_reuses_proposal_but_requires_new_references_and_review():
    from adaptive_document_agent.models import ValidationIssue

    saved, constraint, draft = overflowing()
    draft.decisions[0].disposition = 'covered'
    draft.decisions[0].brief_item_indexes = [0]
    saved.failed_stage = 'source_integration'
    saved.validation_warnings.append(ValidationIssue(code='source_integration_unresolved',
        stage='report', message=json.dumps(dict(attempts=[dict(draft=draft.model_dump(mode='json'))]))))
    current = saved.model_copy(deep=True)

    class RetryGateway(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            assert not issubclass(schema, SourceIntegrationDraft), 'A capacity defect must not regenerate the proposal'
            if schema.__name__ == 'SourceQuoteReferences':
                self.calls.append((messages, schema))
                payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                return schema(decisions_0_evidence=[next(k for k, v in payload['reference_options'].items()
                    if constraint in v['text'])])
            return super().generate_structured(messages, schema, **kwargs)

    gateway = RetryGateway(constraint)
    merged = review_supplementary_sources(gateway, current, current.executive_brief, previous=saved)
    assert resolved_source_check_ids(current, merged) == {'contracts'}
    assert [s.__name__ for _, s in gateway.calls] == ['SourceQuoteReferences', 'SourceIntegrationReview']


def test_nonliteral_quote_repair_cannot_change_claims_sources_or_extend_its_budget():
    from adaptive_document_agent.models.executive_brief import BriefQuote
    result, constraint, draft = overflowing()
    draft.decisions[0].evidence = [BriefQuote(page=12, text='Text stitched across separate source passages.')]
    pages = {p.page_number: p.text for p in result.document.pages}
    before = draft.model_dump(), deepcopy(pages)
    with pytest.raises(SourceQuoteBindingError):
        bind_source_quotes(draft, pages)

    class References:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            packet = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            return schema(decisions_0_evidence=[next(k for k, v in packet['reference_options'].items()
                if constraint in v['text'])])

    gateway, budget = References(), {}
    repaired = bind_with_capacity_repair(gateway, draft, pages, {}, budget)
    assert repaired.decisions[0].model_dump(exclude={'evidence'}) == draft.decisions[0].model_dump(exclude={'evidence'})
    assert normalize(repaired.decisions[0].evidence[0].text) in normalize(pages[12])
    assert (draft.model_dump(), pages) == before
    with pytest.raises(SourceQuoteBindingError):
        bind_with_capacity_repair(gateway, draft, pages, {}, budget)
    assert gateway.calls == 1


def normalize(value):
    return ' '.join(value.split())


def test_complete_invalid_reference_gets_one_field_scoped_format_correction():
    from tests.test_budget_output_v145 import gateway, response
    result, constraint, draft = overflowing()
    pages = {p.page_number: p.text for p in result.document.pages}
    from adaptive_document_agent.agent.source_quote_capacity import reference_options
    _, options = reference_options(pages)
    chosen = next(k for k, v in options.items() if constraint in v['text'])
    llm, client = gateway([response(json.dumps(dict(decisions_0_evidence=['p999:@lines[1]']))),
                           response(json.dumps(dict(decisions_0_evidence=[chosen])))])
    entry, budget = {}, {}
    repaired = bind_with_capacity_repair(llm, draft, pages, entry, budget)
    assert constraint in repaired.decisions[0].evidence[0].text
    assert repaired.decisions[0].model_dump(exclude={'evidence'}) == draft.decisions[0].model_dump(exclude={'evidence'})
    assert len(client.requests) == 2 and budget == dict(quote_capacity=1, quote_capacity_format=1)
    assert entry['quote_reference_format_patch'] == dict(decisions_0_evidence=[chosen])


@pytest.mark.parametrize('kind', ['invalid_again', 'missing', 'malformed', 'refusal'])
def test_reference_format_correction_cannot_loop_or_repair_other_failures(kind):
    from tests.test_budget_output_v145 import gateway, response
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    result, _, draft = overflowing()
    bad = json.dumps(dict(decisions_0_evidence=['p999:@lines[1]']))
    outputs = {'invalid_again': [response(bad), response(bad)], 'missing': [response('{}')],
               'malformed': [response('{')], 'refusal': [response(bad, finish='content_filter')]}[kind]
    llm, client = gateway(outputs)
    with pytest.raises(LLMStructuredOutputError):
        bind_with_capacity_repair(llm, draft, {p.page_number:p.text for p in result.document.pages}, {}, {})
    assert len(client.requests) == (2 if kind == 'invalid_again' else 1)
