"""A failed third review must not poison four siblings or rewrite their copy."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview, meaning_validator
from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
from adaptive_document_agent.agent.brief_review_checkpoint import BriefReviewUnavailable
from adaptive_document_agent.agent.brief_review_progress import brief_progress
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from tests.test_budget_output_v145 import gateway, response
from tests.test_executive_brief import result_for


def fixture():
    texts = [f'Team {letter} provides installation under the disclosed conditions.' for letter in 'ABCDE']
    brief = ExecutiveBrief(items=[ExecutiveBriefItem(label=f'Team {letter}', text=text,
        evidence=[BriefQuote(page=1, text=text)]) for letter, text in zip('ABCDE', texts)])
    result = result_for([' '.join(texts)])
    context = dict(evidence_blocks={'source': result.document.pages[0].text}, source_excerpt_scope=[])
    return brief, result, context


def valid(*indices):
    return response(BriefMeaningReview(items=[dict(index=i, accepted=True,
        numeric_comparison=False, reason='Literal supported statement') for i in indices]))


def directions(*indices):
    return response(BriefClaimDirectionReview(items=[dict(index=i, comparisons=[],
        omitted_directional_claims=[]) for i in indices]))


def failed_sequence():
    cut = lambda: response('', finish='length')
    return [cut(), cut(), valid(0), directions(0), valid(1), directions(1),
            cut(), cut(), valid(3), directions(3), valid(4), directions(4)]


def latest(result):
    return json.loads(next(w.message for w in reversed(result.validation_warnings)
                          if w.code == 'executive_brief_review_checkpoint'))


def test_third_item_capacity_failure_retains_fully_validated_siblings_and_exact_retry():
    brief, result, context = fixture()
    before = deepcopy((brief, result.document, result.observations))
    llm, client = gateway(failed_sequence())
    validate = meaning_validator(llm, result=result, source_context=context)
    progress = []
    with brief_progress(progress.append), pytest.raises(BriefReviewUnavailable) as error:
        validate(brief)
    assert error.value.failures == {2: 'output_capacity_exhausted'}
    checkpoint = latest(result)
    assert checkpoint['checked'] == {'0': [], '1': [], '3': [], '4': []}
    assert checkpoint['pending'] == [2] and checkpoint['unavailable'] == {'2': 'output_capacity_exhausted'}
    assert checkpoint['semantic_approval'] is False
    assert len(client.requests) == 12
    assert [kw['max_tokens'] for _, kw in client.requests if kw['max_tokens'] == 32768] == [32768]
    assert client.requests[6][0] == client.requests[7][0]
    assert any('item 3' in p and 'capacity retry' in p and '32768' in p for p in progress)
    assert any('item 5' in p for p in progress)
    with pytest.raises(BriefReviewUnavailable):
        validate(brief)
    assert len(client.requests) == 12  # No automatic repeated recovery or copy patch.
    resumed, resumed_client = gateway([valid(2), directions(2)])
    assert meaning_validator(resumed, result=result, source_context=context)(brief) == {}
    assert len(resumed_client.requests) == 2
    assert latest(result)['semantic_approval'] is True
    assert (brief, result.document, result.observations) == before


@pytest.mark.parametrize('change', ['companion', 'source', 'shared', 'assurance'])
def test_changed_context_invalidates_previous_checkpoint(change):
    brief, result, context = fixture()
    llm, _ = gateway(failed_sequence())
    with pytest.raises(BriefReviewUnavailable):
        meaning_validator(llm, result=result, source_context=context)(brief)
    if change == 'companion':
        brief.items[4].label = 'Disclosed installation conditions'
    elif change == 'source':
        result.document.pages[0].text += ' Additional operating qualification.'
    elif change == 'shared':
        context['evidence_blocks']['extra'] = 'A later disclosed qualification.'
    else:
        from adaptive_document_agent.models import ValidationIssue
        result.validation_warnings.append(ValidationIssue(code='report_audit_scope_review', stage='report',
            severity='info', message='{}'))
    resumed, client = gateway([valid(0, 1, 2, 3, 4), directions(0, 1, 2, 3, 4)])
    assert meaning_validator(resumed, result=result, source_context=context)(brief) == {}
    assert len(client.requests) == 2
    assert latest(result)['checked'] == {str(i): [] for i in range(5)}


def test_capacity_does_not_enter_existing_source_or_meaning_copy_repair(monkeypatch):
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
    from adaptive_document_agent.services.llm.exceptions import LLMResponseError
    brief, result, context = fixture()
    llm, client = gateway([response(brief), *failed_sequence()])
    def generate(writer, current, **kwargs):
        return generate_with_item_repair(llm, [], result=current,
            excerpts={1: current.document.pages[0].text}, topics=[], source_context=context,
            semantic_validator=meaning_validator(llm, result=current, source_context=context))
    monkeypatch.setattr(ExecutiveBriefWriter, '_generate', generate)
    with pytest.raises(LLMResponseError, match='item 3: output_capacity_exhausted'):
        ExecutiveBriefWriter(llm).generate(result)
    assert len(client.requests) == 13 and result.executive_brief is None
    assert latest(result)['pending'] == [2]
    assert not any(x.get('operation') == 'ExecutiveBriefPatch' for x in llm.usage)


def test_unreviewed_direction_cannot_be_checkpointed_as_approved():
    from adaptive_document_agent.services.llm.exceptions import LLMTransportError
    brief, result, context = fixture()
    llm, _ = gateway([valid(0, 1, 2, 3, 4), LLMTransportError('offline direction review')])
    with pytest.raises(LLMTransportError):
        meaning_validator(llm, result=result, source_context=context)(brief)
    checkpoint = latest(result)
    assert checkpoint['checked'] == {} and checkpoint['semantic_approval'] is False
    assert checkpoint['pending'] == list(range(5))


def test_writer_resumes_only_unfinished_check_without_source_selection_or_draft():
    from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
    brief, result, context = fixture()
    llm, _ = gateway(failed_sequence())
    with pytest.raises(BriefReviewUnavailable):
        meaning_validator(llm, result=result, source_context=context)(brief)
    resumed, client = gateway([valid(2), directions(2)])
    assert ExecutiveBriefWriter(resumed).generate(result) == brief
    assert len(client.requests) == 2
    assert {x['operation'] for x in resumed.usage} == {'BriefMeaningReview', 'BriefClaimDirectionReview'}


def test_background_progress_is_delivered_only_on_waiting_caller(monkeypatch):
    from threading import get_ident
    from types import SimpleNamespace
    from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
    from adaptive_document_agent.agent.prepared_executive_brief import prepare_executive_brief
    from adaptive_document_agent.agent.brief_review_progress import report_brief_progress
    brief, result, _ = fixture()
    caller, events = get_ident(), []
    def generate(self, current, **kwargs):
        assert get_ident() != caller
        report_brief_progress('item 3; capacity retry 2/2, output limit 32768')
        return brief
    monkeypatch.setattr(ExecutiveBriefWriter, 'generate', generate)
    with brief_progress(lambda text: events.append((get_ident(), text))):
        with prepare_executive_brief(SimpleNamespace(discovery_workers=2), result, timings={}) as prepared:
            assert prepared.result(result) == brief
    assert len(events) == 1 and events[0][0] == caller and 'item 3' in events[0][1]


def test_review_progress_keeps_one_stage_clock_and_workflow_percentage():
    from adaptive_document_agent.ui.processing_progress import ProcessingProgress
    now = [100.0]
    progress = ProcessingProgress(None, clock=lambda: now[0])
    progress.update('Planning presentation narrative')
    now[0] = 120
    progress.update('Writing the evidence-bound executive briefing')
    sequence = progress.stage_sequence
    for message in ['item 3 (3/5 pending); request 1/2, output limit 16384',
                    'item 3 (3/5 pending); capacity retry 2/2, output limit 32768',
                    '4/5 item checks completed']:
        now[0] += 100
        progress.update('Briefing review: ' + message)
        assert progress.stage_sequence == sequence and progress.stage_started_at == 120
        assert progress.percent == 85 and progress.stage_id == 'executive_briefing'
