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
    from adaptive_document_agent.services.pipeline_completion import require_source_integration
    with pytest.raises(ValueError, match=r'contracts: expected a literal quotation on PDF page 12'):
        require_source_integration(result)


def test_review_uses_original_pdf_text_for_numbered_line_ranges():
    result, constraint = fixture()
    result.document.pages[11].text = f'Adjacent heading\r\n{constraint}\r\nSeparate column'
    class LineGateway(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            output = super().generate_structured(messages, schema, **kwargs)
            if schema is SourceIntegrationDraft:
                assert '2 | ' + constraint in messages[-1]['content']
                output.decisions[0].evidence[0].text = '@lines[2-2]'
                output.additions[0].evidence[0].text = '@lines[2] ' + constraint
            return output
    gateway = LineGateway(constraint)
    result.executive_brief = review_supplementary_sources(gateway, result, result.executive_brief)
    assert resolved_source_check_ids(result, result.executive_brief) == {'contracts'}
    assert result.executive_brief.items[-1].evidence[0].text == constraint
    reviewer = gateway.calls[-1][0]
    assert '@lines[' not in reviewer[-1]['content'] and constraint in reviewer[-1]['content']
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['attempts'][0]['submitted_draft']['decisions'][0]['evidence'][0]['text'] == '@lines[2-2]'


@pytest.mark.parametrize('reference', ['@lines[0]', '@lines[99]', '@lines[2-1]'])
def test_invalid_source_line_references_stop_before_review(reference):
    result, constraint = fixture()
    gateway = Gateway(constraint, quote=reference)
    original = result.executive_brief.model_copy(deep=True)
    assert review_supplementary_sources(gateway, result, original) == original
    assert all(schema is SourceIntegrationDraft for _, schema in gateway.calls)
    assert 'Invalid evidence range' in json.loads(result.validation_warnings[-1].message)['reason']


def test_numbered_pages_offer_only_size_valid_literal_ranges_without_dropping_source():
    from adaptive_document_agent.agent.source_integration_quotes import numbered_source_pages, bind_source_quotes
    from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
    text = '\n'.join(f'Condition {i}: obligations and limitations stay in the original evidence.' for i in range(90))
    page = numbered_source_pages([dict(page=12, text=text)])[0]
    assert [line.split(' | ', 1)[1] for line in page['lines']] == text.splitlines()
    assert len(page['evidence_reference_options']) > 1
    for option in page['evidence_reference_options']:
        draft = SourceIntegrationDraft(decisions=[dict(section_id='conditions', disposition='omit',
            reason='Representative original source.', evidence=[dict(page=12, text=option['ref'])])])
        resolved = bind_source_quotes(draft, {12: text}).decisions[0].evidence[0].text
        assert resolved in text and len(resolved) == option['characters']
        assert 8 <= len(resolved) <= 1800
    whole = SourceIntegrationDraft(decisions=[dict(section_id='conditions', disposition='omit',
        reason='Keep every selected condition.', evidence=[dict(page=12, text='@lines[1-90]')])])
    pieces = bind_source_quotes(whole, {12: text}).decisions[0].evidence
    assert len(pieces) == 4 and all(q.page == 12 and 8 <= len(q.text) <= 1800 for q in pieces)
    assert ''.join(q.text for q in pieces) == text
    assert all(q.text.endswith('\n') for q in pieces[:-1])
    assert whole.decisions[0].evidence[0].text == '@lines[1-90]'


def test_split_reference_preserves_siblings_when_the_minimum_split_needs_a_word_boundary():
    from adaptive_document_agent.agent.source_integration_quotes import bind_source_quotes
    from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
    text = '\r\n'.join(['A' * 1000, 'middle ' * 200, 'B' * 1000])
    quotes = [dict(page=1, text='@lines[1-3]'), dict(page=2, text='Original sibling.'),
              dict(page=3, text='@lines[1]')]
    draft = SourceIntegrationDraft(decisions=[dict(section_id='source', disposition='omit',
        reason='Complete source choice.', evidence=quotes)])
    resolved = bind_source_quotes(draft, {1:text, 3:'Last sibling.'}).decisions[0].evidence
    assert [q.page for q in resolved] == [1, 1, 2, 3]
    assert resolved[0].text + resolved[1].text == text
    assert [q.text for q in resolved[2:]] == ['Original sibling.', 'Last sibling.']


def test_addition_and_disposition_keep_their_own_capacity_for_identical_selected_lines():
    from adaptive_document_agent.agent.source_integration_quotes import bind_source_quotes
    from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
    text = '\n'.join([str(i) * 1500 for i in range(6)])
    evidence = [dict(page=1, text='@lines[1-6]')]
    draft = SourceIntegrationDraft(decisions=[], additions=[
        dict(label='Finding', text='The source is qualified.', evidence=evidence)])
    pieces = bind_source_quotes(draft, {1:text}).additions[0].evidence
    assert len(pieces) == 6 and ''.join(q.text for q in pieces) == text
    small = SourceIntegrationDraft(decisions=[dict(section_id='scope', disposition='omit',
        reason='Complete source choice.', evidence=evidence)])
    with pytest.raises(ValueError, match='at most 4'):
        bind_source_quotes(small, {1:text})


@pytest.mark.parametrize('locator,source,error', [
    ('@lines[1] Different transcription.', 'Original passage. ' * 120, 'Transcription differs'),
    ('@lines[1]', 'X' * 1801, 'has 1801 characters'),
    ('@lines[1]', 'short', 'has 5 characters'),
])
def test_subdivision_cannot_repair_a_wrong_transcription_or_invalid_literal(locator, source, error):
    from adaptive_document_agent.agent.source_integration_quotes import bind_source_quotes
    from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
    draft = SourceIntegrationDraft(decisions=[dict(section_id='scope', disposition='omit',
        reason='Complete source choice.', evidence=[dict(page=1, text=locator)])])
    with pytest.raises(ValueError, match=error):
        bind_source_quotes(draft, {1:source})


def test_literal_quote_does_not_override_rejected_semantic_review():
    result, constraint = fixture()
    result.executive_brief = ExecutiveBrief.model_validate(payload(constraint, 12, 'Contract risk'))
    assert not uncited_source_checks(result, result.executive_brief)
    gateway = Gateway(constraint, accept=False, disposition='covered')
    result.executive_brief = review_supplementary_sources(gateway, result, result.executive_brief)
    assert uncited_source_checks(result, result.executive_brief)
