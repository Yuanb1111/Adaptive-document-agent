"""A citation-capacity correction preserves copy and cannot grant source approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_integration_review import (
    SourceIntegrationDraft, review_supplementary_sources, resolved_source_check_ids,
)
from adaptive_document_agent.agent.source_integration_quotes import SourceQuoteCapacityError, bind_source_quotes
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
def test_reference_repair_still_requires_independent_source_review(accepted):
    result, constraint, draft = overflowing()
    original = result.executive_brief.model_copy(deep=True)
    source = deepcopy(result.document)

    class ReviewGateway(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            if schema is SourceIntegrationDraft:
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
            assert schema is not SourceIntegrationDraft, 'A capacity defect must not regenerate the proposal'
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
