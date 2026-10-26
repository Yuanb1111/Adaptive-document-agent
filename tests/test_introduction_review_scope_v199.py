"""Current placement is ledger data; source judgments still need model repair/review."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.agent.introduction_audience_review import binding_errors
from adaptive_document_agent.agent.introduction_review_scope import bind_finding_scope
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.test_introduction_current_context import Reviewer, run
from tests.test_introduction_mixed_flow_v149 import SyntheticMixedFlowGateway, mixed_flow_fixture
from tests.test_introduction_review_binding_v143 import review_context
from tests.test_introduction_review_source_binding import response


@pytest.mark.parametrize('include', [True, False])
def test_part_tag_comes_from_current_ledger_without_changing_rejection_or_selection(include):
    reading, payload = review_context()
    value = response(payload, kind='included_part' if include else 'omitted_part')
    value.findings[0].kind = 'omitted_part' if include else 'included_part'
    value.repair_scope = 'meanings'
    original = deepcopy((value, payload, reading.parts))
    budget = {'used': False}
    client = Reviewer(lambda *_: value)
    bound = run(client, reading, payload, budget=budget)
    assert not bound.accepted and not reading.audience_selection
    assert bound.findings[0].kind == ('included_part' if include else 'omitted_part')
    assert bound.repair_scope == ('meanings' if include else 'selection')
    assert bound.reason == value.reason
    for field in ('part_id', 'meaning_id', 'current_meaning', 'issue_type', 'reason'):
        assert getattr(bound.findings[0], field) == getattr(value.findings[0], field)
    assert (value, payload, reading.parts) == original
    assert len(client.requests) == 1 and budget['used'] is False
    record = reading.plan_audits[-1]['introduction_audience_review']
    assert record['raw_review'] == value.model_dump(mode='json')
    assert record['review'] == bound.model_dump(mode='json')
    assert record['status'] == 'bound'
    assert record['finding_scope_binding']['semantic_approval'] is False
    assert record['finding_scope_binding']['findings'][0]['current_include'] is include
    assert not binding_errors(bound, payload)


def test_valid_omitted_finding_routes_to_selection_even_with_meanings_scope():
    _, payload = review_context()
    value = response(payload, kind='omitted_part', quote=payload['source']['parts'][1]['source_text'])
    value.repair_scope = 'meanings'
    bound, audit = bind_finding_scope(value, payload)
    assert bound.repair_scope == 'selection' and bound.findings == value.findings
    assert audit['findings'] == [] and audit['repair_scope']['omitted_part_ids'] == ['part-1']
    assert not binding_errors(bound, payload)


@pytest.mark.parametrize('fault', ['unknown_part', 'duplicate_source', 'duplicate_decision',
    'stale_digest', 'foreign_quote', 'empty_quote', 'meaning_id', 'current_meaning', 'accepted'])
def test_placement_binding_never_guesses_ownership_or_repairs_other_invalid_output(fault):
    _, payload = review_context()
    value = response(payload, kind='omitted_part', quote=payload['source']['parts'][1]['source_text'])
    value.findings[0].kind = 'included_part'
    value.repair_scope = 'meanings'
    if fault == 'unknown_part': value.findings[0].part_id = 'unknown'
    elif fault == 'duplicate_source': payload['source']['parts'].append(deepcopy(payload['source']['parts'][1]))
    elif fault == 'duplicate_decision': payload['decisions'].append(deepcopy(payload['decisions'][1]))
    elif fault == 'stale_digest': value.selection_digest = 'stale'
    elif fault == 'foreign_quote': value.findings[0].source_quote = 'A foreign unsupported source passage.'
    elif fault == 'empty_quote': value.findings[0].source_quote = ''
    elif fault == 'meaning_id': value.findings[0].meaning_id = 'part-0:meaning-1'
    elif fault == 'current_meaning': value.findings[0].current_meaning = 'Old assertion.'
    else: value.accepted = True
    original = deepcopy((value, payload))
    bound, audit = bind_finding_scope(value, payload)
    assert bound == value and audit == dict(findings=[], semantic_approval=False)
    assert binding_errors(bound, payload)
    assert (value, payload) == original


@pytest.mark.parametrize('final_verdict', ['accept', 'reject', 'unavailable', 'stale'])
def test_mislabeled_omission_reaches_full_mixed_repair_and_fresh_independent_review(final_verdict):
    class MislabeledReviewer(SyntheticMixedFlowGateway):
        def generate_structured(self, messages, schema, **kwargs):
            value = super().generate_structured(messages, schema, **kwargs)
            if schema.__name__ == 'IntroductionAudienceReview' and len(self.reviews) == 2:
                # Recorded failure shape: an omitted part is tagged included,
                # alongside genuine findings on currently included meanings.
                value.findings[1].kind = 'included_part'
                value.repair_scope = 'meanings'
            return value
    result, reading = mixed_flow_fixture()
    original_parts = deepcopy(reading.parts)
    client = MislabeledReviewer(reading, final_verdict)
    if final_verdict in {'accept', 'stale'}:
        select_introduction_audience(client, result, reading)
        assert reading.audience_selection['independent_review']['accepted'] is True
        assert 'part-2' in reading.audience_part_ids
    else:
        with pytest.raises((ValueError, LLMResponseError)):
            select_introduction_audience(client, result, reading)
        assert not reading.audience_selection
    assert reading.parts == original_parts
    assert len(client.resolution_requests) == 1
    assert len(client.resolution_requests[0]['findings']) == 4
    records = [a['introduction_audience_review'] for a in reading.plan_audits
               if 'introduction_audience_review' in a]
    prior = records[1]
    assert prior['raw_review']['findings'][1]['kind'] == 'included_part'
    assert prior['review']['findings'][1]['kind'] == 'omitted_part'
    assert prior['review']['accepted'] is False and prior['review']['repair_scope'] == 'selection'
    assert records[2]['selection_digest'] != prior['selection_digest']
    assert client.calls[:5] == ['IntroductionAudienceSelection', 'IntroductionAudienceReview',
        'IntroductionMeaningRevision', 'IntroductionAudienceReview', 'IntroductionMeaningResolution']
    assert not prior['re_review']
