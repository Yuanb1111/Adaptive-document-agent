"""Disposition evidence is copied from exact owners, never retyped or semantically approved."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience_review import (
    IntroductionAudienceReview, review_current_selection)
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    IntroductionMeaningResolution, apply_meaning_resolution, resolve_meaning_findings)
from adaptive_document_agent.agent.introduction_review_history import resolution_wire
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_introduction_meaning_resolution_v147 import resolution_fixture


class ResolutionGateway:
    def __init__(self, response):
        self.response = response
        self.messages = []

    def generate_structured(self, messages, schema, **kwargs):
        self.messages.append(deepcopy(messages))
        assert schema is IntroductionMeaningResolution
        return schema.model_validate(self.response.model_dump())


def resolve_fixture(proposed_quote=''):
    _, reading, source, selection, findings, response = resolution_fixture()
    response.finding_dispositions[0].source_quote = proposed_quote
    verdict = IntroductionAudienceReview(accepted=False, reason='Review the complete owned union.',
        repair_scope='meanings', findings=[{key: value for key, value in finding.items()
                                          if key != 'finding_id'} for finding in findings])
    return reading, source, selection, verdict, response


@pytest.mark.parametrize('proposed_quote', ['', 'Staff training is required before delivery.',
    'The system schedules appointments. Inspections limit capacity.',
    'A quotation from a different source or invented by the model.'])
def test_resolution_copies_complete_owned_evidence_and_retains_raw_proposal(proposed_quote):
    reading, source, selection, verdict, response = resolve_fixture(proposed_quote)
    before = deepcopy((source, selection, verdict, response))
    client = ResolutionGateway(response)
    draft, ledger = resolve_meaning_findings(client, source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading)
    record = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert (source, selection, verdict, response) == before
    assert draft == selection
    assert record['response'] == response.model_dump(mode='json')
    assert record['response_source_quotes_status'] == 'untrusted_diagnostic_only'
    assert record['response']['finding_dispositions'][0]['source_quote'] == proposed_quote
    assert ledger['finding_dispositions'][0]['source_quote'] == source['parts'][0]['source_text']
    assert record['bound_finding_dispositions'] == ledger['finding_dispositions']
    assert record['status'] == 'protocol_validated'
    assert record['semantic_approval'] is ledger['semantic_approval'] is False
    assert not reading.audience_selection and reading.audience_part_ids is None
    assert 'leave EVERY disposition source_quote empty' in client.messages[0][0]['content']


def test_disposition_quote_may_be_omitted_but_low_level_apply_still_requires_literal_evidence():
    _, source, selection, verdict, response = resolve_fixture()
    wire = response.model_dump()
    wire['finding_dispositions'][0].pop('source_quote')
    parsed = IntroductionMeaningResolution.model_validate(wire)
    assert parsed.finding_dispositions[0].source_quote == ''
    findings = [dict(finding_id='finding-0', **verdict.findings[0].model_dump())]
    for proposal in ('', 'The system schedules appointments. Inspections limit capacity.'):
        parsed.finding_dispositions[0].source_quote = proposal
        with pytest.raises(ValueError, match='lacks literal evidence from its own source part'):
            apply_meaning_resolution(selection, parsed, findings, source)


@pytest.mark.parametrize('fault', ['unknown_finding', 'duplicate_disposition', 'missing_disposition',
    'foreign_finding_owner', 'stale_meaning', 'unbound_original_quote', 'unknown_reference',
    'foreign_reference', 'duplicate_reference', 'duplicate_source_part'])
def test_canonical_binding_cannot_authorize_wrong_addresses_or_unowned_references(fault):
    reading, source, selection, verdict, response = resolve_fixture()
    disposition = response.finding_dispositions[0]
    if fault == 'unknown_finding':
        disposition.finding_id = 'unknown'
    elif fault == 'duplicate_disposition':
        response.finding_dispositions.append(disposition.model_copy(deep=True))
    elif fault == 'missing_disposition':
        response.finding_dispositions.clear()
    elif fault == 'foreign_finding_owner':
        verdict.findings[0].part_id = 'part-1'
    elif fault == 'stale_meaning':
        verdict.findings[0].current_meaning = 'Historical assertion no longer in the current draft.'
    elif fault == 'unbound_original_quote':
        verdict.findings[0].source_quote = 'An invented review quotation.'
    elif fault == 'unknown_reference':
        disposition.referenced_meaning_ids = ['unknown']
    elif fault == 'foreign_reference':
        disposition.referenced_meaning_ids = ['part-1:meaning-1']
    elif fault == 'duplicate_reference':
        disposition.referenced_meaning_ids *= 2
    else:
        source['parts'].append(deepcopy(source['parts'][0]))
    before = deepcopy((source, selection, verdict, response))
    # Empty response lists are possible after a caller mutation; the protocol
    # validator, rather than a second schema parse, must still reject them.
    class Gateway:
        def generate_structured(self, *args, **kwargs):
            return response
    with pytest.raises(ValueError):
        resolve_meaning_findings(Gateway(), source, selection,
            selection.model_dump(mode='json')['decisions'], verdict, reading)
    assert (source, selection, verdict, response) == before
    record = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert record['status'] == 'failed' and 'semantic_approval' not in record
    assert record['response'] == response.model_dump(mode='json')
    assert not reading.audience_selection and reading.audience_part_ids is None


def canonical_ledger():
    reading, source, selection, verdict, response = resolve_fixture(
        'The system schedules appointments. Inspections limit capacity.')
    _, ledger = resolve_meaning_findings(ResolutionGateway(response), source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading)
    return reading, source, selection, ledger


def test_review_wire_references_exact_canonical_disposition_source_without_changing_audit():
    reading, source, _, ledger = canonical_ledger()
    before = deepcopy((source, ledger, reading.plan_audits))
    wire = resolution_wire(ledger, source=source)
    disposition = wire['finding_dispositions'][0]
    assert disposition['source_part_ref'] == ledger['findings'][0]['part_id'] == 'part-0'
    assert 'source_quote' not in disposition and 'proposed_source_quote' not in disposition
    assert disposition['reason'] == ledger['finding_dispositions'][0]['reason']
    assert wire['semantic_approval'] is False
    assert (source, ledger, reading.plan_audits) == before
    assert resolution_wire(ledger)['finding_dispositions'][0]['source_quote'] == source['parts'][0]['source_text']


@pytest.mark.parametrize('fault', ['foreign_canonical_quote', 'foreign_source_reference',
    'unknown_finding', 'duplicate_finding', 'duplicate_disposition', 'missing_disposition'])
def test_wire_never_hides_corrupt_canonical_disposition_binding(fault):
    _, source, _, ledger = canonical_ledger()
    if fault == 'foreign_canonical_quote':
        ledger['finding_dispositions'][0]['source_quote'] = source['parts'][1]['source_text']
    elif fault == 'foreign_source_reference':
        ledger['findings'][0]['part_id'] = 'part-1'
    elif fault == 'unknown_finding':
        ledger['finding_dispositions'][0]['finding_id'] = 'unknown'
    elif fault == 'duplicate_finding':
        ledger['findings'].append(deepcopy(ledger['findings'][0]))
    elif fault == 'duplicate_disposition':
        ledger['finding_dispositions'].append(deepcopy(ledger['finding_dispositions'][0]))
    else:
        ledger['finding_dispositions'].clear()
    before = deepcopy(ledger)
    with pytest.raises(ValueError):
        resolution_wire(ledger, source=source)
    assert ledger == before


@pytest.mark.parametrize('accepted', [True, False])
def test_canonical_disposition_evidence_still_requires_fresh_independent_semantic_review(accepted):
    reading, source, selection, ledger = canonical_ledger()
    values = selection.model_dump(mode='json')['decisions']
    before = deepcopy((source, selection, values, ledger))
    class Reviewer:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert schema is IntroductionAudienceReview
            payload = review_payload(messages)
            row = payload['meaning_resolution']['finding_dispositions'][0]
            assert row['source_part_ref'] == 'part-0' and 'source_quote' not in row
            assert payload['source']['parts'] == source['parts']
            assert 'independently judge each proposed classification' in messages[0]['content']
            return review_response(schema, messages, accepted=accepted,
                repair_scope='meanings', reason='A fresh independent source judgment.',
                findings=[] if accepted else [dict(kind='included_part', issue_type='new_assertion',
                    part_id='part-0', source_quote='A historical pilot ran in 2019.',
                    reason='A synthetic reviewer still requires this context.')])
    reviewer = Reviewer()
    verdict = review_current_selection(reviewer, source, values, 'Review full source.', reading,
        attempt=2, meaning_revision_base=values, inventory_revision_base=None,
        binding_budget={'used': False}, meaning_resolution=ledger)
    assert verdict.accepted is accepted and reviewer.calls == 1
    assert (source, selection, values, ledger) == before
    assert not reading.audience_selection and reading.audience_part_ids is None
