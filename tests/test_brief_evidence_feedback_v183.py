from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_source_reference_repair import owned_evidence_options, append_owned_evidence
from adaptive_document_agent.agent.brief_source_repair import correct_residual_source_errors
from adaptive_document_agent.agent.brief_period_clarification import period_clarification_options
from adaptive_document_agent.agent.brief_status_conflict import retryable_status_conflict
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for, payload
from tests.test_brief_targeted_contract_v147 import comparison_case, Replies


def reference_case():
    fact = 'The programme met Rule 27B.04(2) requirements in 2024.'
    tail = 'The programme remains subject to funding uncertainty.'
    result = result_for([fact + '\n' + tail, 'Another programme enrolled 99 people.'])
    brief = ExecutiveBrief.model_validate(payload(fact))
    brief.items[0].evidence[0].text = tail
    catalog = {'head': {'page': 1, 'text': fact}, 'tail': {'page': 1, 'text': tail},
               'other': {'page': 2, 'text': result.document.pages[1].text}}
    return result, brief, catalog


def test_residual_patch_can_select_missing_same_page_quote_without_replacing_existing_evidence():
    result, brief, catalog = reference_case()
    before = deepcopy(brief)
    errors = {'item_0': ['Initial numeric source failure.'], 'item_1': ['A corrected sibling.']}
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            context = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert set(context['evidence_options']['item_0']) == {'head'}
            return schema(item_0={'text': brief.items[0].text, 'append_evidence_refs': ['head']})
    audit = {}
    corrected = correct_residual_source_errors(Client(), brief, result=result,
        excerpts={p.page_number: p.text for p in result.document.pages}, initial_errors=errors,
        audit=audit, evidence_catalog=catalog)
    assert corrected and not validate_executive_brief(corrected, result)
    assert corrected.items[0].evidence[:-1] == before.items[0].evidence
    assert corrected.items[0].text == before.items[0].text
    assert brief == before
    assert audit['residual_source_correction']['semantic_approval'] is False


@pytest.mark.parametrize('refs', [['other'], ['missing'], ['head', 'head'], ['tail']])
def test_unknown_cross_page_duplicate_or_existing_refs_are_rejected(refs):
    _, brief, catalog = reference_case()
    with pytest.raises(ValueError):
        append_owned_evidence(brief.items[0], refs, owned_evidence_options(brief.items[0], catalog))


def test_forged_catalog_text_still_fails_literal_source_gate():
    result, brief, catalog = reference_case()
    catalog['head']['text'] = brief.items[0].text + ' Invented facts.'
    candidate = append_owned_evidence(brief.items[0], ['head'], owned_evidence_options(brief.items[0], catalog))
    assert validate_executive_brief(ExecutiveBrief(items=[candidate]), result)


def test_additions_cannot_exceed_original_quote_limit():
    _, brief, catalog = reference_case()
    item = brief.items[0]
    item.evidence.extend(item.evidence[0].model_copy(update={'text': f'Existing source passage {i}.'}) for i in range(3))
    with pytest.raises(ValueError):
        append_owned_evidence(item, ['head'], owned_evidence_options(item, catalog))


def test_relative_comparison_uses_latest_endpoint_not_an_earlier_comparison():
    result, brief = comparison_case()
    brief.items[0].text = ('Fees were USD 1,250 thousand in 6M2023 versus USD 1,475 thousand in 6M2024, '
                           'and fees at June 30, 2024 were USD 1,475 thousand versus USD 1,250 thousand a year earlier.')
    options = period_clarification_options(brief.items[0], result)
    assert {o['clarified_prior_period'] for o in options} == {'6M2023'}
    brief.items[0].text = 'Fees were USD 1,475 thousand in 6M2024. They were USD 1,250 thousand a year earlier.'
    assert not period_clarification_options(brief.items[0], result)  # No cross-sentence inference.


@pytest.mark.parametrize('period', ['6M2023', 'June 30, 2023'])
def test_conflicting_status_is_retryable_but_never_accepted(period):
    from adaptive_document_agent.agent.brief_audit_scope import source_audit_scope
    result, brief = comparison_case()
    inventory = source_audit_scope(brief.items[0], result)
    conflict = deepcopy(inventory[0])
    conflict['table_id'] = 'other'
    for column in conflict['columns']:
        column['status'] = 'unknown'
    inventory.append(conflict)
    error = f"Audit status 'unaudited' for '{period}' lacks unambiguous source column support"
    assert retryable_status_conflict(error, inventory)
    assert not retryable_status_conflict(error.replace('unaudited', 'audited'), inventory)
    assert not retryable_status_conflict(error.replace('2023', '2022'), inventory)


def test_conflict_correction_is_bounded_and_gets_fresh_independent_review(monkeypatch):
    from adaptive_document_agent.agent import brief_semantic_repair as repair
    from adaptive_document_agent.agent.brief_audit_scope import source_audit_scope
    result, brief = comparison_case()
    original = deepcopy(brief)
    inventory = source_audit_scope(brief.items[0], result)
    conflict = deepcopy(inventory[0])
    for column in conflict['columns']:
        column['status'] = 'unknown'
    inventory.append(conflict)
    monkeypatch.setattr(repair, 'source_audit_scope', lambda *a, **k: inventory)
    invalid = brief.items[0].text + ' 6M2023 (unaudited).'
    valid = brief.items[0].text.replace('up from', 'compared with')
    for fixed in (True, False):
        replies = Replies([{'item_0': {'text': invalid}}, {'item_0': {'text': valid if fixed else invalid}}])
        reviewed = []
        def review(value):
            reviewed.append(deepcopy(value))
            return {0: ['State a neutral comparison.']} if value == original else {}
        audit = {}
        corrected = repair.correct_new_meaning_errors(replies, brief, result=result,
            excerpts={1: result.document.pages[0].text}, topics=[], source_context={}, evidence_catalog=None,
            semantic_validator=review, audit=audit)
        assert len(replies.calls) == 2
        assert (corrected is not None) is fixed
        assert len(reviewed) == (2 if fixed else 1)
        assert brief == original


def test_missing_brief_reports_original_failure_before_source_integration(monkeypatch):
    from adaptive_document_agent.agent import prepared_executive_brief
    from tests.test_reporting_checkpoint_v144 import _coverage_fixture, _run_coverage_fixture, SyntheticCoverageFlowClient
    source, raw = _coverage_fixture()
    def rejected(*args, **kwargs):
        raise ValueError('Retained briefing has conflicting source qualifications.')
    monkeypatch.setattr(prepared_executive_brief, 'current_executive_brief', rejected)
    result = _run_coverage_fixture(monkeypatch, source, raw, SyntheticCoverageFlowClient(source))
    assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    assert result.failed_stage == 'executive_brief'
    assert result.failure_details['component'] == 'ExecutiveBrief'
    assert 'conflicting source qualifications' in result.failure_details['message']
    assert not any(w.code == 'source_integration_failed' for w in result.validation_warnings)
