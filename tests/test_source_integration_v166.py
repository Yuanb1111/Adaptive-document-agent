"""An actual independent source decision, never a wording change, clears scope."""
import json
from copy import deepcopy

import pytest

from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.agent.source_integration_review import (
    SourceIntegrationDraft, review_supplementary_sources, resolved_source_check_ids,
)
from adaptive_document_agent.agent.brief_source_checks import uncited_source_checks
from tests.test_brief_source_checks import sample
from tests.test_executive_brief import payload


class Gateway:
    def __init__(self, constraint, *, accept=True, disposition='include', quote=None):
        self.constraint, self.accept, self.disposition = constraint, accept, disposition
        self.quote = quote or constraint
        self.calls = []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((messages, schema))
        if schema is SourceIntegrationDraft:
            return schema(additions=payload(self.constraint, 12, 'Contract risk')['items']
                          if self.disposition == 'include' else [], decisions=[dict(
                section_id='contracts', disposition=self.disposition,
                reason='Cancellation rights qualify demand certainty.' if self.disposition == 'include'
                else 'The existing conclusion already states the cancellation constraint.',
                evidence=[dict(page=12, text=self.quote)],
                brief_item_indexes=[1] if self.disposition == 'include' else [0])])
        return schema(verdicts=[dict(section_id='contracts', accepted=self.accept,
            reason='The cited cancellation condition is faithfully included.' if self.accept
            else 'The source limitation is not sufficiently represented.')])


def fixture():
    result, constraint = sample()
    result.executive_brief = ExecutiveBrief.model_validate(payload('Revenue was USD 12 million.'))
    return result, constraint


def test_material_source_finding_is_added_only_after_independent_review():
    result, constraint = fixture()
    original = result.executive_brief.model_copy(deep=True)
    source = deepcopy(result.document.model_dump())
    gateway = Gateway(constraint)
    result.executive_brief = review_supplementary_sources(gateway, result, original)
    assert result.executive_brief.items[0] == original.items[0]
    assert result.executive_brief.items[1].text == constraint
    assert len(gateway.calls) == 2
    assert not uncited_source_checks(result, result.executive_brief)
    assert resolved_source_check_ids(result, result.executive_brief) == {'contracts'}
    assert result.document.model_dump() == source
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['draft']['decisions'][0]['disposition'] == 'include'
    assert audit['review']['verdicts'][0]['accepted']
    assert review_supplementary_sources(gateway, result, result.executive_brief) == result.executive_brief
    assert len(gateway.calls) == 2


def test_independent_rejection_cannot_clear_scope_or_add_unapproved_copy():
    result, constraint = fixture()
    original = result.executive_brief.model_copy(deep=True)
    gateway = Gateway(constraint, accept=False)
    assert review_supplementary_sources(gateway, result, original) == original
    assert not resolved_source_check_ids(result, original)
    assert uncited_source_checks(result, original)
    assert result.validation_warnings[-1].code == 'source_integration_unresolved'
    assert len(gateway.calls) == 4  # One bounded correction and fresh independent review.


@pytest.mark.parametrize('mutation', ['brief', 'source', 'check'])
def test_review_verdict_expires_when_its_bound_context_changes(mutation):
    result, constraint = fixture()
    result.executive_brief = review_supplementary_sources(Gateway(constraint), result, result.executive_brief)
    assert resolved_source_check_ids(result, result.executive_brief)
    if mutation == 'brief':
        result.executive_brief.items[0].text += ' Changed interpretation.'
    elif mutation == 'source':
        result.document.pages[11].text += ' Additional qualification.'
    else:
        result.profile.source_coverage.checks[0].status = 'incomplete'
    assert not resolved_source_check_ids(result, result.executive_brief)


def test_forged_quote_is_rejected_before_independent_approval():
    result, constraint = fixture()
    gateway = Gateway(constraint, quote='Customers cannot cancel purchases.')
    original = result.executive_brief.model_copy(deep=True)
    assert review_supplementary_sources(gateway, result, original) == original
    assert all(schema is SourceIntegrationDraft for _, schema in gateway.calls)
    assert not resolved_source_check_ids(result, original)


def test_literal_quote_does_not_override_rejected_semantic_review():
    result, constraint = fixture()
    result.executive_brief = ExecutiveBrief.model_validate(payload(constraint, 12, 'Contract risk'))
    assert not uncited_source_checks(result, result.executive_brief)
    gateway = Gateway(constraint, accept=False, disposition='covered')
    result.executive_brief = review_supplementary_sources(gateway, result, result.executive_brief)
    assert uncited_source_checks(result, result.executive_brief)
