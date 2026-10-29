"""Broad context and exact claim gates are independent, mandatory and resumable."""
from concurrent.futures import CancelledError
from copy import deepcopy
import json
from threading import Barrier, get_ident

import pytest

from adaptive_document_agent.agent.brief_context_review import (
    BriefContextReview, CONTEXT_INSTRUCTIONS, review_context, split_context_review,
)
from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
from adaptive_document_agent.agent.brief_review_checkpoint import BriefReviewUnavailable
from adaptive_document_agent.agent.brief_review_progress import brief_progress
from tests.test_brief_review_checkpoint_v215 import fixture, latest
from tests.test_brief_meaning_capacity_v213 import payload
from tests.test_budget_output_v145 import gateway, response


def large_fixture():
    brief, result, context = fixture()
    # Distinct original blocks, including a material final block, are all retained.
    context['evidence_blocks'].update({f'b{i}': f'Page {i}: ' + 'Literal original context. ' * 180
                                       for i in range(10)})
    context['evidence_blocks']['last'] = 'The later matched-period outcome reverses the earlier increase.'
    return brief, result, context


class ReviewGateway:
    def __init__(self, *, workers=1, context_reject=False, claim_reject=False, context_failure=None):
        self.discovery_workers = workers
        self.calls = []
        self.barrier = Barrier(2) if workers > 1 else None
        self.context_reject = context_reject
        self.claim_reject = claim_reject
        self.context_failure = context_failure

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((schema.__name__, deepcopy(messages), get_ident()))
        if schema.__name__ == 'BriefClaimDirectionReview':
            return schema(items=[dict(index=i, comparisons=[]) for i in range(5)])
        rows = payload(messages)
        if self.barrier:
            self.barrier.wait(timeout=5)
        if schema is BriefContextReview:
            if self.context_failure:
                raise self.context_failure
            return schema(items=[dict(index=row['index'], accepted=not self.context_reject,
                reason='Block last materially qualifies this conclusion.' if self.context_reject
                       else 'The whole brief retains all material qualifications.') for row in rows])
        return schema(items=[dict(index=row['index'], accepted=not self.claim_reject,
            numeric_comparison=False, reason='Literal item source check.') for row in rows])


@pytest.mark.parametrize('workers', [1, 2])
def test_full_context_retained_and_both_gates_run_under_gateway_concurrency(workers):
    brief, result, context = large_fixture()
    original = deepcopy((brief, context, result.document))
    llm = ReviewGateway(workers=workers)
    caller, progress = get_ident(), []
    with brief_progress(lambda value: progress.append((get_ident(), value))):
        assert meaning_validator(llm, result=result, source_context=context)(brief) == {}
    calls = {name: (messages, thread) for name, messages, thread in llm.calls}
    claims, source_thread = calls['BriefMeaningReview']
    broad, context_thread = calls['BriefContextReview']
    claim_rows, context_rows = payload(claims), payload(broad)
    assert context_rows[0]['available_report_context']['evidence_blocks'] == context['evidence_blocks']
    assert context_rows[0]['available_report_context']['current_brief'] == brief.model_dump(mode='json')
    assert claim_rows[0]['available_report_context'] == {'current_brief': brief.model_dump(mode='json')}
    assert [r['item'] for r in claim_rows] == [r['item'] for r in context_rows]
    assert [r['source_audit_scope'] for r in claim_rows] == [r['source_audit_scope'] for r in context_rows]
    assert len(claims[1]['content']) < len(broad[1]['content']) / 4
    assert (source_thread != context_thread) == (workers > 1)
    assert all(thread == caller for thread, _ in progress)
    assert latest(result)['semantic_approval'] is True
    assert (brief, context, result.document) == original


@pytest.mark.parametrize('rejected_gate', ['claim', 'context'])
def test_either_gate_rejection_blocks_approval_and_is_memoized(rejected_gate):
    brief, result, context = large_fixture()
    llm = ReviewGateway(context_reject=rejected_gate == 'context', claim_reject=rejected_gate == 'claim')
    validate = meaning_validator(llm, result=result, source_context=context)
    errors = validate(brief)
    assert set(errors) == set(range(5))
    count = len(llm.calls)
    assert validate(brief) == errors and len(llm.calls) == count
    assert latest(result)['semantic_approval'] is False


def test_context_failure_never_certifies_claims_that_already_passed():
    brief, result, context = large_fixture()
    failure = BriefReviewUnavailable({i: 'context_output_capacity_exhausted' for i in range(5)})
    llm = ReviewGateway(context_failure=failure)
    with pytest.raises(BriefReviewUnavailable):
        meaning_validator(llm, result=result, source_context=context)(brief)
    assert latest(result)['checked'] == {}
    assert latest(result)['semantic_approval'] is False


def test_context_output_is_bounded_and_partial_json_never_approves():
    complete = BriefContextReview(items=[dict(index=3, accepted=True, reason='Complete context checked.')])
    messages = [dict(role='system', content=CONTEXT_INSTRUCTIONS), dict(role='user', content='Full context')]
    llm, client = gateway([response(complete, finish='length'), response(complete)])
    record = {}
    assert review_context(llm, messages, [3], record, None) == {}
    assert [kw['max_tokens'] for _, kw in client.requests] == [16384, 32768]
    assert client.requests[0][0] == client.requests[1][0]
    llm, client = gateway([response(complete, finish='length')] * 2)
    with pytest.raises(BriefReviewUnavailable) as error:
        review_context(llm, messages, [3], {}, None)
    assert error.value.failures == {3: 'context_output_capacity_exhausted'}


@pytest.mark.parametrize('indices', [[], [0], [3, 3]])
def test_context_verdict_requires_exact_indices(indices):
    answer = BriefContextReview(items=[dict(index=i, accepted=True, reason='Checked.') for i in indices])
    llm, _ = gateway([response(answer)])
    with pytest.raises(ValueError, match='every exact supplied index'):
        review_context(llm, [], [3], {}, None)


def test_first_request_cancelled_candidate_is_saved_and_writer_resumes():
    from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
    from tests.test_brief_review_checkpoint_v215 import valid, directions
    brief, result, context = fixture()
    llm, _ = gateway([CancelledError('shared analysis deadline')])
    with pytest.raises(CancelledError):
        meaning_validator(llm, result=result, source_context=context)(brief)
    saved = latest(result)
    assert saved['candidate'] == brief.model_dump(mode='json') and saved['source_context'] == context
    assert saved['checked'] == {} and saved['pending'] == list(range(5))
    assert saved['semantic_approval'] is False
    retry, client = gateway([valid(0, 1, 2, 3, 4), directions(0, 1, 2, 3, 4)])
    assert ExecutiveBriefWriter(retry).generate(result) == brief
    assert len(client.requests) == 2


def test_small_context_retains_existing_single_review_path():
    brief, result, context = fixture()
    llm = ReviewGateway()
    assert meaning_validator(llm, result=result, source_context=context)(brief) == {}
    assert [name for name, _, _ in llm.calls] == ['BriefMeaningReview', 'BriefClaimDirectionReview']


@pytest.mark.parametrize('mutation', ['direction', 'foreign_reference', 'unequal_duration'])
def test_context_acceptance_cannot_override_exact_source_and_arithmetic_failures(mutation):
    from tests.test_brief_review_bindings_v139 import setup_review
    from tests.brief_direction_fixture import accepted_directions
    brief, result, original, corrected = setup_review()
    _, _, context = large_fixture()
    verdicts = [corrected['items'][0], original['items'][1]]
    comparison = verdicts[0]['comparisons'][0]
    if mutation == 'direction':
        comparison['direction'] = 'decrease'
    elif mutation == 'foreign_reference':
        comparison['start_ref'] = 'i1_q0'
    else:
        comparison['end_duration_months'] = 6

    class Gate:
        def generate_structured(self, messages, schema, **kwargs):
            if schema is BriefContextReview:
                return schema(items=[dict(index=i, accepted=True, reason='Context sufficient.') for i in range(2)])
            if schema.__name__ == 'BriefClaimDirectionReview':
                return accepted_directions(messages, schema, verdicts)
            return schema(items=deepcopy(verdicts))

    errors = meaning_validator(Gate(), result=result, source_context=context)(brief)
    assert set(errors) == {0}
    assert latest(result)['semantic_approval'] is False


def test_split_cancellation_does_not_launch_context_request_in_serial_mode():
    from adaptive_document_agent.agent.brief_context_parallel import prepared_context_review
    from threading import Event
    stop = Event()
    llm, client = gateway([])
    with prepared_context_review(llm, [], [0], {}, cancelled=stop) as finish:
        stop.set()
        with pytest.raises(CancelledError):
            finish()
    assert client.requests == []
