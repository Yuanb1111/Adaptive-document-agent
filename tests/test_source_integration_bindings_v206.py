"""Three originals plus two additions have five reviewable, exact addresses."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_integration_review import (
    SourceIntegrationDraft, review_supplementary_sources, resolved_source_check_ids,
)
from adaptive_document_agent.models.coverage import SourceCheck
from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from tests.test_source_integration_v166 import fixture
from tests.test_executive_brief import payload


def case():
    result, constraint = fixture()
    for label, text in [('Operations', 'Operations continued.'), ('Demand', 'Demand remained uncertain.')]:
        result.document.pages[0].text += '\n' + text
        result.executive_brief.items.append(ExecutiveBriefItem.model_validate(payload(text, 1, label)['items'][0]))
    other = 'The forecast depends on continued customer renewals.'
    result.document.pages[11].text += '\n' + other
    result.profile.source_coverage.checks.append(SourceCheck(section_id='outlook', pages=[12],
        reason='Read forecast conditions.', decision_impact='Qualifies expected demand.',
        status='checked_found', finding=other, evidence_quotes={12: [other]}))
    draft = SourceIntegrationDraft(additions=[
        payload(constraint, 12, 'Cancellation')['items'][0],
        payload(other, 12, 'Forecast conditions')['items'][0]], decisions=[
            dict(section_id=sid, disposition='include', reason='Material source qualification.',
                 evidence=[dict(page=12, text=text)], brief_item_indexes=[index])
            for sid, text, index in [('contracts', constraint, 3), ('outlook', other, 4)]])
    return result, draft


@pytest.mark.parametrize('accepted', [True, False])
def test_reviewer_sees_exact_addition_at_index_four_and_still_owns_semantic_verdict(accepted):
    result, draft = case()
    original = result.executive_brief.model_copy(deep=True)
    sources = deepcopy(result.document)
    class Gateway:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if schema is SourceIntegrationDraft:
                return draft.model_copy(deep=True)
            context = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert context['original_brief_item_count'] == 3
            assert context['original_brief'] == original.model_dump(mode='json')
            ledger = context['merged_brief_items']
            assert [row['index'] for row in ledger] == list(range(5))
            assert [row['origin'] for row in ledger] == ['original'] * 3 + ['addition'] * 2
            assert ledger[4]['item'] == draft.additions[1].model_dump(mode='json')
            assert context['resolved_source_bindings'][1]['items'] == [dict(index=4, origin='addition')]
            assert context['source_pages'][0]['text'] == result.document.pages[11].text
            return schema(verdicts=[dict(section_id=d.section_id, accepted=accepted,
                reason='Exact added item carries the source condition.' if accepted else
                       'The bound finding misses a material condition.') for d in draft.decisions])
    gateway = Gateway()
    result.executive_brief = review_supplementary_sources(gateway, result, original)
    assert result.document == sources
    assert result.executive_brief.items[:3] == original.items
    if accepted:
        assert len(result.executive_brief.items) == 5
        assert resolved_source_check_ids(result, result.executive_brief) == {'contracts', 'outlook'}
        assert gateway.calls == 2
    else:
        assert result.executive_brief == original
        assert not resolved_source_check_ids(result, original)
        assert gateway.calls == 4


@pytest.mark.parametrize('mutation', ['out_of_range', 'covered_addition', 'include_original'])
def test_invalid_addresses_never_reach_the_independent_reviewer(mutation):
    result, draft = case()
    if mutation == 'out_of_range':
        draft.decisions[1].brief_item_indexes = [5]
    elif mutation == 'covered_addition':
        draft.decisions[1].disposition = 'covered'
    else:
        draft.decisions[1].brief_item_indexes = [0]
    class Gateway:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert schema is SourceIntegrationDraft
            return draft
    gateway = Gateway()
    original = result.executive_brief.model_copy(deep=True)
    assert review_supplementary_sources(gateway, result, original) == original
    assert gateway.calls == 2
    assert not resolved_source_check_ids(result, original)
