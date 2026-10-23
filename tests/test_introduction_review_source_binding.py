"""Source references avoid model transcription without weakening review gates."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience_review import (
    IntroductionAudienceReview, binding_errors,
)
from adaptive_document_agent.agent.introduction_review_context import bind_finding_sources
from tests.test_introduction_current_context import Reviewer, fresh_acceptance, run
from tests.test_introduction_review_binding_v143 import review_context, meaning_finding


def response(payload, *, kind='meaning', quote=''):
    finding = meaning_finding(payload)
    finding.update(source_quote=quote, issue_type='missing_qualification')
    if kind != 'meaning':
        finding.update(kind=kind, meaning_id='', current_meaning='')
    if kind == 'omitted_part':
        finding['part_id'] = 'part-1'
    return IntroductionAudienceReview(accepted=False, reason='A current qualifier needs repair.',
        repair_scope='selection', selection_digest=payload['current_selection_digest'], findings=[finding])


@pytest.mark.parametrize('kind', ['meaning', 'included_part', 'omitted_part'])
def test_reference_materializes_exact_owned_evidence_without_accepting_or_mutating(kind):
    reading, payload = review_context()
    original = response(payload, kind=kind)
    snapshot = original.model_dump()
    client = Reviewer(lambda *_: original)
    budget = {'used': False}
    verdict = run(client, reading, payload, budget=budget)
    assert verdict.accepted is False and not reading.audience_selection
    assert not budget['used'] and len(client.requests) == 1
    part = next(p for p in reading.parts if p.id == verdict.findings[0].part_id)
    assert verdict.findings[0].source_quote == part.source_text
    assert original.model_dump() == snapshot
    expected = deepcopy(snapshot)
    expected['findings'][0]['source_quote'] = part.source_text
    assert verdict.model_dump() == expected
    record = reading.plan_audits[-1]['introduction_audience_review']
    assert record['raw_review'] == snapshot
    assert record['review'] == expected and record['status'] == 'bound'
    assert record['finding_source_bindings'] == [dict(finding_index=0,
        source_part_ref=part.id, binding='complete_owned_source', semantic_approval=False)]
    assert not binding_errors(verdict, payload)


def test_disconnected_sentences_still_fail_but_fresh_reference_preserves_the_rejection():
    reading, payload = review_context()
    first = 'The six-axis models primarily use the A series.'
    middle = 'These models have a flexible design.'
    last = 'The four-axis models primarily use the B series.'
    source = first + '\n' + middle + '\n' + last
    reading.parts[0].source_text = source
    payload['source']['parts'][0]['source_text'] = source
    # Regression shape from analysis.680: two literal sentences with an omitted middle sentence.
    def spliced(schema, messages, wire):
        return response({**payload, 'current_selection_digest': wire['current_selection_digest']},
                        quote=first + ' ' + last)
    def referenced(schema, messages, wire):
        assert wire['binding_recheck']['findings'][0]['source_quote_is_literal'] is False
        assert wire['binding_recheck']['findings'][0]['returned_source_quote'] == first + ' ' + last
        assert wire['binding_recheck']['findings'][0]['source_part_ref'] == 'part-0'
        assert 'leave source_quote empty' in messages[0]['content']
        assert wire['source']['parts'][0]['source_text'] == source
        return response({**payload, 'current_selection_digest': wire['current_selection_digest']})
    client = Reviewer(spliced, referenced)
    verdict = run(client, reading, payload)
    assert not verdict.accepted and verdict.findings[0].source_quote == source
    assert not reading.audience_selection and len(client.requests) == 2
    records = [a['introduction_audience_review'] for a in reading.plan_audits]
    assert [r['status'] for r in records] == ['invalid_binding', 'bound']
    assert records[0]['raw_review']['findings'][0]['source_quote'] == first + ' ' + last
    assert records[0]['finding_source_bindings'] == []


@pytest.mark.parametrize('fault', ['unknown_part', 'wrong_owner', 'stale_meaning', 'wrong_digest',
    'foreign_quote', 'whitespace_quote', 'accepted_with_findings', 'no_findings'])
def test_reference_never_repairs_unrelated_invalid_bindings_or_authorizes_acceptance(fault):
    reading, payload = review_context()
    value = response(payload)
    if fault == 'unknown_part': value.findings[0].part_id = 'unknown'
    elif fault == 'wrong_owner': value.findings[0].part_id = 'part-1'
    elif fault == 'stale_meaning': value.findings[0].current_meaning = 'An obsolete assertion.'
    elif fault == 'wrong_digest': value.selection_digest = 'obsolete'
    elif fault == 'foreign_quote': value.findings[0].source_quote = 'Foreign evidence.'
    elif fault == 'whitespace_quote': value.findings[0].source_quote = '  '
    elif fault == 'accepted_with_findings': value.accepted = True
    else: value.findings = []
    client = Reviewer(lambda *_: value, lambda *_: value, fresh_acceptance)
    with pytest.raises(ValueError, match='invalid current-draft binding'):
        run(client, reading, payload)
    assert len(client.requests) == 2 and not reading.audience_selection


@pytest.mark.parametrize('fault', ['empty', 'ambiguous'])
def test_missing_or_ambiguous_source_is_never_materialized(fault):
    _, payload = review_context()
    if fault == 'empty': payload['source']['parts'][0]['source_text'] = '\n  '
    else: payload['source']['parts'].append(deepcopy(payload['source']['parts'][0]))
    verdict, bindings = bind_finding_sources(response(payload), payload)
    assert verdict.findings[0].source_quote == '' and bindings == []
    assert binding_errors(verdict, payload)


def test_binding_validator_does_not_itself_trust_unmaterialized_references():
    _, payload = review_context()
    assert binding_errors(response(payload), payload)


def test_complete_source_survives_serialization_without_the_old_quote_length_cap():
    _, payload = review_context()
    text = 'Complete source evidence with necessary qualifications.\n' * 400
    payload['source']['parts'][0]['source_text'] = text
    bound, _ = bind_finding_sources(response(payload), payload)
    reloaded = IntroductionAudienceReview.model_validate_json(bound.model_dump_json())
    assert reloaded.findings[0].source_quote == text
    assert not binding_errors(reloaded, payload)


def test_successful_acceptance_still_requires_empty_findings_and_is_preserved():
    reading, payload = review_context()
    verdict = run(Reviewer(fresh_acceptance), reading, payload)
    record = reading.plan_audits[-1]['introduction_audience_review']
    assert verdict.accepted and verdict.findings == []
    assert record['raw_review'] == record['review']
    assert record['finding_source_bindings'] == []


@pytest.mark.parametrize('accept', [True, False])
def test_reference_findings_enter_semantic_repair_and_require_fresh_acceptance(accept):
    from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
    from tests.test_compact_summary_v111 import fixture
    from tests.test_introduction_meaning_repair_v137 import MeaningClient

    class ReferenceReviewer(MeaningClient):
        def generate_structured(self, messages, schema, **kwargs):
            value = super().generate_structured(messages, schema, **kwargs)
            if schema is IntroductionAudienceReview:
                for finding in value.findings:
                    finding.source_quote = ''
            return value

    result, reading, _ = fixture(3)
    client = ReferenceReviewer(reading, accept=accept)
    if accept:
        select_introduction_audience(client, result, reading)
        assert reading.audience_selection['independent_review']['accepted'] is True
        assert len(reading.audience_selection['decisions'][0]['required_meanings']) == 2
    else:
        with pytest.raises(ValueError, match='not independently accepted'):
            select_introduction_audience(client, result, reading)
        assert not reading.audience_selection
    assert 'IntroductionMeaningRevision' in client.calls
    records = [a['introduction_audience_review'] for a in reading.plan_audits
               if 'introduction_audience_review' in a]
    assert len(records) >= 2 and all(r['status'] == 'bound' for r in records)
    assert all(not r['re_review'] for r in records)
    assert records[0]['review']['accepted'] is False
    assert records[-1]['review']['accepted'] is accept
