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


@pytest.mark.parametrize('mixed_pages', [False, True])
def test_checks_in_the_same_outline_section_still_require_independent_verdicts(mixed_pages):
    from adaptive_document_agent.services.pipeline_completion import source_review_complete

    result, constraint = fixture()
    coverage = result.profile.source_coverage
    other = 'Renewal terms are still under negotiation.'
    result.document.pages[10].text = other
    coverage.checks.append(coverage.checks[0].model_copy(update={
        'pages': [11], 'finding': other, 'evidence_quotes': {11: [other]},
    }))
    check_ids = list(coverage.checks_by_review_id())
    assert len(check_ids) == len(set(check_ids)) == 2
    draft = SourceIntegrationDraft(decisions=[dict(section_id='contracts', disposition='omit',
        reason='Synthetic test disposition.', evidence=[dict(page=page, text=quote)])
        for page, quote in [(12, constraint), (11, other)]])
    if mixed_pages:
        draft.decisions[0].evidence.extend(draft.decisions[1].evidence)

    class CheckGateway:
        def generate_structured(self, messages, schema, **kwargs):
            if schema is SourceIntegrationDraft:
                assert any(all(key in message['content'] for key in check_ids) for message in messages)
                return draft.model_copy(deep=True)
            assert not mixed_pages
            payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert [d['section_id'] for d in payload['draft']['decisions']] == check_ids
            return schema(verdicts=[dict(section_id=key, accepted=True, reason='Synthetic review.')
                                    for key in check_ids])

    assert not source_review_complete(result)
    result.executive_brief = review_supplementary_sources(CheckGateway(), result, result.executive_brief)
    assert source_review_complete(result) is not mixed_pages
    assert all(c.section_id == 'contracts' for c in coverage.checks)


def test_first_overlong_addition_keeps_sources_through_copy_and_independent_review():
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    result, constraint = fixture()

    class CopyGateway(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            if not self.calls:
                raw = super().generate_structured(messages, schema, **kwargs).model_dump()
                raw['additions'][0]['text'] *= 60
                raw['additions'][0]['label'] *= 12
                raise LLMStructuredOutputError('Overlong addition', response=LLMResponse(text=json.dumps(raw)))
            if schema.__name__ == 'SourceAdditionCopy':
                self.calls.append((messages, schema))
                return schema(addition_0_label='Contract risk', addition_0_text=constraint)
            return super().generate_structured(messages, schema, **kwargs)

    gateway = CopyGateway(constraint)
    merged = review_supplementary_sources(gateway, result, result.executive_brief)
    assert [s.__name__ for _, s in gateway.calls] == [
        'SourceIntegrationDraft', 'SourceAdditionCopy', 'SourceIntegrationReview']
    assert resolved_source_check_ids(result, merged) == {'contracts'}
    assert merged.items[1].evidence[0].text == constraint


@pytest.mark.parametrize('same_context', [False, True])
def test_retry_revalidates_proposal_and_requires_fresh_section_verdicts(same_context):
    saved, constraint = fixture()
    review_supplementary_sources(Gateway(constraint, accept=False), saved, saved.executive_brief)
    saved.failed_stage = 'source_integration'
    audit = json.loads(saved.validation_warnings[-1].message)
    for entry in audit['attempts']:
        entry.pop('review')
    saved.validation_warnings[-1].message = json.dumps(audit)
    current = saved.model_copy(deep=True)
    if not same_context:
        current.executive_brief.title = 'Changed briefing'
    gateway = Gateway(constraint)
    merged = review_supplementary_sources(gateway, current, current.executive_brief, previous=saved)
    assert resolved_source_check_ids(current, merged) == {'contracts'}
    assert len(gateway.calls) == (1 if same_context else 2)
    assert gateway.calls[-1][1].__name__ == 'SourceIntegrationReview'


def test_rejected_source_proposal_carries_objections_into_revision_before_fresh_review():
    saved, constraint = fixture()
    review_supplementary_sources(Gateway(constraint, accept=False), saved, saved.executive_brief)
    saved.failed_stage = 'source_integration'
    current = saved.model_copy(deep=True)
    gateway = Gateway(constraint)
    merged = review_supplementary_sources(gateway, current, current.executive_brief, previous=saved)
    assert gateway.calls[0][1] is SourceIntegrationDraft
    assert 'The source limitation is not sufficiently represented.' in gateway.calls[0][0][-2]['content']
    assert resolved_source_check_ids(current, merged) == {'contracts'}


def test_missing_inclusion_address_only_binds_one_exclusively_owned_addition():
    from types import SimpleNamespace as Row
    from adaptive_document_agent.agent.source_integration_bindings import bind_unique_inclusions
    decision = Row(section_id='alpha', disposition='include', brief_item_indexes=[])
    addition = Row(evidence=[Row(page=2)])
    draft = Row(decisions=[decision], additions=[addition])
    checks = {'alpha': Row(pages=[2, 3]), 'beta': Row(pages=[2, 4])}
    assert not bind_unique_inclusions(draft, checks, 4)
    checks['beta'].pages = [4]
    draft.additions.append(addition)
    assert not bind_unique_inclusions(draft, checks, 4)
    draft.additions.pop()
    assert bind_unique_inclusions(draft, checks, 4) == {'alpha': 4}
    assert decision.brief_item_indexes == [4]


def test_only_unambiguous_whole_one_based_inclusion_ledger_is_normalized():
    from types import SimpleNamespace as Row
    from adaptive_document_agent.agent.source_integration_bindings import bind_unique_inclusions
    decisions = [Row(section_id=str(i), disposition='include', brief_item_indexes=[i + 5]) for i in range(2)]
    checks = {str(i): Row(pages=[i + 1]) for i in range(2)}
    draft = Row(decisions=decisions, additions=[Row(evidence=[Row(page=p)]) for p in (1, 2)])
    decisions[0].brief_item_indexes = [4]
    assert not bind_unique_inclusions(draft, checks, 4)
    decisions[0].brief_item_indexes = [5]
    assert bind_unique_inclusions(draft, checks, 4) == {'0': 4, '1': 5}
    assert [d.brief_item_indexes for d in decisions] == [[4], [5]]


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
