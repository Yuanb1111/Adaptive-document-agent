"""Accepted evidence is immutable topic content, never a provisional decision."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.coverage_merge_contract import merge_response_model
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_coverage_review import review_topic_coverage
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.pipeline_completion import require_topic_coverage, topic_coverage_complete
from tests.test_budget_output_v145 import gateway, response
from tests.test_coverage_completion_v174 import prepared


@pytest.mark.parametrize('fault', ['extra', 'missing', 'duplicate', 'blank'])
def test_merge_schema_and_local_validator_bind_only_requested_ids(monkeypatch, fault):
    _, _, selected, _, delta, valid, _ = prepared(monkeypatch)
    ids = [d.series_id for d in delta.coverage_decisions]
    schema = merge_response_model(ids)
    wire = schema.model_json_schema()
    ledger = wire['properties']['coverage_decisions']
    definition = wire['$defs'][ledger['items']['$ref'].split('/')[-1]]
    assert definition['properties']['series_id']['enum'] == ids
    assert ledger['minItems'] == ledger['maxItems'] == len(ids)
    assert schema.__name__ == 'TopicCoverageReview'
    assert schema.model_validate(valid.model_dump()).model_dump() == valid.model_dump()
    rejected = valid.model_dump()
    if fault == 'extra':
        rejected['coverage_decisions'].append(dict(series_id=selected.topics[0].series_ids[0],
            decision='omit', reason='A mistaken description of an already accepted measure.'))
    elif fault == 'missing': rejected['coverage_decisions'].pop()
    elif fault == 'duplicate': rejected['coverage_decisions'][1] = deepcopy(rejected['coverage_decisions'][0])
    else: rejected['coverage_decisions'][0]['reason'] = ' '
    before = deepcopy(rejected)
    with pytest.raises(ValidationError, match='Coverage delta must decide'):
        schema.model_validate(rejected)
    assert rejected == before


@pytest.mark.parametrize('fixed', [True, False])
def test_gateway_retries_unknown_decision_once_without_dropping_source(monkeypatch, fixed):
    result, lookup, selected, raw, delta, valid, _ = prepared(monkeypatch)
    before = deepcopy((selected, result.observations))
    extra = 'unknown-source'
    rejected = valid.model_dump()
    rejected['coverage_decisions'].append(dict(series_id=extra, decision='omit',
        reason='This misidentified accepted measure is secondary.'))
    llm, client = gateway([response(delta), response(json.dumps(rejected)),
                           response(valid if fixed else json.dumps(rejected))])
    result.presentation_topics = review_topic_coverage(selected, result, lookup, set(), raw, llm,
                                                       PresentationTopicSelector._validate)
    assert len(client.requests) == 3
    audit = json.loads(result.validation_warnings[-1].message)
    attempts = audit['merge']['attempts']
    assert len(attempts) == 2 and extra in attempts[0]['validation_error']
    assert attempts[0]['invalid_response'] == json.dumps(rejected)
    correction = client.requests[-1][0]
    assert correction[:len(client.requests[1][0])] == client.requests[1][0]
    assert 'Remove the unexpected ledger entry, not the accepted observations' in correction[-1]['content']
    assert (selected, result.observations) == before
    if fixed:
        assert result.presentation_topics.topics == valid.topics and topic_coverage_complete(result)
        assert selected.topics[0].series_ids[0] in {sid for t in result.presentation_topics.topics for sid in t.series_ids}
    else:
        assert result.presentation_topics == selected and not topic_coverage_complete(result)
        with pytest.raises(ValueError, match='Original coverage failure:.*Coverage delta'):
            require_topic_coverage(result)


@pytest.mark.parametrize('message', ['not JSON', '[]', '{"reason":123}', '{"reason":"Exact ledger failure"}'])
def test_completion_diagnostic_handles_legacy_and_structured_audits(monkeypatch, message):
    result, *_ = prepared(monkeypatch)
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_coverage_unresolved',
        severity='warning', stage='presentation', message=message))
    with pytest.raises(ValueError, match='Presentation source coverage review') as error:
        require_topic_coverage(result)
    assert ('Original coverage failure: Exact ledger failure' in str(error.value)) == ('Exact ledger failure' in message)


@pytest.mark.parametrize('decision', ['include', 'omit'])
def test_accepted_echo_is_audited_without_repeating_merge_or_losing_evidence(monkeypatch, decision):
    result, lookup, selected, raw, delta, valid, _ = prepared(monkeypatch)
    before = deepcopy((selected, result.observations))
    extra = dict(series_id=selected.topics[0].series_ids[0], decision=decision,
                 reason='Misidentified accepted measure; this must never enter report copy.')
    draft = valid.model_dump()
    draft['coverage_decisions'].append(extra)
    llm, client = gateway([response(delta), response(json.dumps(draft))])
    result.presentation_topics = review_topic_coverage(selected, result, lookup, set(), raw, llm,
                                                       PresentationTopicSelector._validate)
    assert len(client.requests) == 2
    assert result.presentation_topics.topics == valid.topics and topic_coverage_complete(result)
    assert (selected, result.observations) == before
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['merge']['review']['coverage_decisions'] == draft['coverage_decisions']
    echo = audit['merge']['accepted_decision_echoes']
    assert echo['decisions'] == [extra]
    assert echo['accepted_source_observations_preserved'] is True
    assert echo['omission_reasons_used_as_evidence'] is False
    assert extra['series_id'] not in {d['series_id'] for d in audit['review']['coverage_decisions']}
    assert extra['reason'] not in result.presentation_topics.model_dump_json()


@pytest.mark.parametrize('fault', ['lost_original', 'false_include', 'unknown', 'duplicate', 'missing', 'blank', 'invented_period'])
def test_accepted_echo_cannot_hide_invalid_merge(monkeypatch, fault):
    result, lookup, selected, raw, delta, valid, _ = prepared(monkeypatch)
    extra = dict(series_id=selected.topics[0].series_ids[0], decision='omit', reason='Outside scope.')
    draft = valid.model_dump()
    draft['coverage_decisions'].append(extra)
    if fault == 'lost_original': draft['topics'] = draft['topics'][1:]
    elif fault == 'false_include': draft['topics'] = draft['topics'][:1]
    elif fault == 'unknown': draft['coverage_decisions'].append({**extra, 'series_id': 'unknown-source'})
    elif fault == 'duplicate': draft['coverage_decisions'].append(extra.copy())
    elif fault == 'missing': draft['coverage_decisions'].pop(0)
    elif fault == 'blank': draft['coverage_decisions'][-1]['reason'] = ' '
    else: draft['topics'][0]['takeaway'] = 'The result rose in FY2037.'
    llm, client = gateway([response(delta), response(json.dumps(draft)), response(json.dumps(draft))])
    result.presentation_topics = review_topic_coverage(selected, result, lookup, set(), raw, llm,
                                                       PresentationTopicSelector._validate)
    assert len(client.requests) == 3 and result.presentation_topics == selected
    assert not topic_coverage_complete(result)
    audit = json.loads(result.validation_warnings[-1].message)
    assert 'accepted_decision_echoes' not in audit['merge']
    with pytest.raises(ValueError, match='source coverage review'):
        require_topic_coverage(result)
