"""Reading reuse binds complete immutable inputs and never lends semantic approval."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models import (
    DocumentPage, DocumentProfile, Observation, ParsedDocument, PipelineResult, SourceEvidence,
)
from adaptive_document_agent.models.coverage import SourceSection
from adaptive_document_agent.models.summary import (
    SummaryFact, SummaryFactRef, SummaryPageRange, SummaryPart, SummaryPartDecision,
    SummaryReview, SummarySlideItem, SummarySlidePage,
)
from adaptive_document_agent.services import summary_validation as validation
from adaptive_document_agent.services.compact_summary import compact_digest
from adaptive_document_agent.services.summary_source import source_blocks
from adaptive_document_agent.utils.validation_memo import ValidationMemo


@pytest.fixture
def checks(monkeypatch):
    # Keep the real deterministic validator; observe only whether it executes.
    monkeypatch.setattr(validation, '_reading_memo', ValidationMemo())
    original, calls = validation._reading_errors, []
    def checked(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(validation, '_reading_errors', checked)
    return calls


def source():
    body = ('The service provides scheduling software for manufacturing teams and requires '
            'staff training before delivery.')
    text = 'SUMMARY\n' + body
    result = PipelineResult(document=ParsedDocument(document_id='memo-source', sha256='fixed-identity',
        safe_filename='source.pdf', page_count=2, pages=[
            DocumentPage(page_number=1, text=text, raw_text=text, text_blocks=[{'lines': [
                {'text': 'SUMMARY', 'bbox': [30, 20, 200, 35]},
                {'text': body, 'bbox': [30, 100, 500, 140]}]}]),
            DocumentPage(page_number=2, text='A separate supporting passage.')]),
        profile=DocumentProfile(), observations=[Observation(id='reported-volume',
            metric_original='Reported volume', value=10, raw_value='10', confidence=1,
            evidence=[SourceEvidence(page=1, text=body, extraction_method='fixture', confidence=1)])])
    blocks = source_blocks(result, [1])
    review = SummaryReview(document_id=result.document.document_id,
        document_sha256=result.document.sha256, source_pages=[1], source_blocks=blocks,
        scope_ranges=[SummaryPageRange(start_page=1, end_page=1, reason='Complete source scope.')],
        parts=[SummaryPart(id='heading', title='Source heading', role='heading', block_id=blocks[0].id,
            start_line=1, end_line=1, source_page=1, source_text='SUMMARY\n',
            reading_note='The literal heading identifies this source section.'),
            SummaryPart(id='operations', title='Operations', role='content', block_id=blocks[0].id,
            start_line=2, end_line=2, source_page=1, source_text=body,
            reading_note='The service scope includes its delivery condition.', facts=[
                SummaryFact(label='Service scope', text=body, source_quote=body, source_pages=[1])])])
    return result, review


def test_equal_deepcopies_reuse_reading_without_mutating_result_or_review(checks):
    result, review = source()
    before_result, before_review = result.model_dump_json(), review.model_dump_json()
    assert validation.reading_errors(review, result) == []
    assert validation.reading_errors(deepcopy(review), deepcopy(result)) == []
    assert len(checks) == 1
    assert result.model_dump_json() == before_result and review.model_dump_json() == before_review


@pytest.mark.parametrize('mutation', [
    'raw_value', 'numeric_value', 'observation_evidence', 'source_text', 'raw_text',
    'geometry', 'outline', 'reading_fact', 'reading_note', 'source_block', 'scope_range',
    'review_document_identity', 'source_pages',
])
def test_source_observation_geometry_and_reading_changes_invalidate_the_memo(checks, mutation):
    result, review = source()
    assert validation.reading_errors(review, result) == []
    if mutation == 'raw_value': result.observations[0].raw_value = '11'
    elif mutation == 'numeric_value': result.observations[0].value = 11
    elif mutation == 'observation_evidence': result.observations[0].evidence[0].text = 'Different retained evidence.'
    elif mutation == 'source_text': result.document.pages[0].text += '\nAdditional source passage.'
    elif mutation == 'raw_text': result.document.pages[0].raw_text += '\nAdditional raw extraction.'
    elif mutation == 'geometry': result.document.pages[0].text_blocks[0]['lines'][0]['bbox'][1] = 120
    elif mutation == 'outline': result.document.outline.append(SourceSection(
        id='extra-scope', title='SUMMARY', start_page=2, end_page=2))
    elif mutation == 'reading_fact': review.parts[1].facts[0].source_quote = 'An unowned alternative source.'
    elif mutation == 'reading_note': review.parts[1].reading_note = 'There are 999 unsupported operations.'
    elif mutation == 'source_block': review.source_blocks[0].text += ' Altered source.'
    elif mutation == 'scope_range': review.scope_ranges[0].end_page = 2
    elif mutation == 'review_document_identity': review.document_sha256 = 'another-source'
    else: review.source_pages = [2]
    errors = validation.reading_errors(review, result)
    assert len(checks) == 2
    if mutation in {'source_text', 'outline', 'reading_fact', 'reading_note', 'source_block',
                    'scope_range', 'review_document_identity', 'source_pages'}:
        assert errors
    # These mutations deliberately retain the document SHA. Source contents,
    # geometry and raw values must not borrow approval from that stable label.
    assert result.document.sha256 == 'fixed-identity'


def test_complete_scope_mode_has_its_own_reading_result(checks):
    result, review = source()
    result.document.outline.append(SourceSection(id='additional', title='SUMMARY', start_page=2, end_page=2))
    assert validation.reading_errors(review, result, complete_scope=True)
    assert validation.reading_errors(review, result, complete_scope=False) == []
    assert validation.reading_errors(review, result, complete_scope=True)
    assert len(checks) == 2


def test_returned_errors_cannot_mutate_the_memo_diagnostics(checks):
    result, review = source()
    review.parts[1].reading_note = 'The unsupported count is 999.'
    first = validation.reading_errors(review, result)
    expected = first[:]
    assert expected
    first.clear()
    first.append('Caller-injected diagnostic')
    assert validation.reading_errors(review, result) == expected
    assert len(checks) == 1


def compact_source():
    result, review = source()
    fact = review.parts[1].facts[0]
    pages = [SummarySlidePage(id='opening', title='Service delivery', source_section='Operations', compact=True,
        items=[SummarySlideItem(label=fact.label, text=fact.text, source_quote=fact.source_quote,
            source_pages=fact.source_pages, part_ids=['operations'],
            source_refs=[SummaryFactRef(part_id='operations', fact_index=0)])])]
    review.decisions = [SummaryPartDecision(part_id='heading', decision='omit', reason='Source heading.'),
                        SummaryPartDecision(part_id='operations', decision='include', reason='Required service scope.')]
    review.plan_audits = [dict(compact_digest=compact_digest(pages), compact_semantic_review=dict(
        opening_accepted=True, parts=[dict(part_id='operations', accepted=True,
                                         reason='The service and its training condition are expressed.')]))]
    return result, review, pages


@pytest.mark.parametrize('mutation', ['opening_rejected', 'part_rejected', 'wrong_digest', 'removed_audit'])
def test_changed_semantic_verdict_is_rechecked_even_when_reading_hits_cache(checks, mutation):
    result, review, pages = compact_source()
    assert validation.presentation_errors(review, pages, result) == []
    saved = deepcopy(review.plan_audits)
    if mutation == 'opening_rejected': review.plan_audits[0]['compact_semantic_review']['opening_accepted'] = False
    elif mutation == 'part_rejected': review.plan_audits[0]['compact_semantic_review']['parts'][0]['accepted'] = False
    elif mutation == 'wrong_digest': review.plan_audits[0]['compact_digest'] = 'a-different-visible-copy'
    else: review.plan_audits = []
    assert any('independent complete part-meaning review' in error
               for error in validation.presentation_errors(review, pages, result))
    assert len(checks) == 1
    review.plan_audits = saved
    assert validation.presentation_errors(review, pages, result) == []
    assert len(checks) == 1


def test_new_visible_copy_cannot_reuse_semantic_acceptance_from_reading_cache(checks):
    result, review, pages = compact_source()
    assert validation.presentation_errors(review, pages, result) == []
    pages[0].items[0].text = 'The service provides scheduling software for manufacturing teams.'
    assert any('independent complete part-meaning review' in error
               for error in validation.presentation_errors(review, pages, result))
    assert len(checks) == 1
