"""A model-assembled identity is editable when no retained entity was supplied."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditBindingValidationError, AuditScopeDraft, AuditScopeReview, _context, _validate,
    review_report_audit_scope, require_report_audit_scope,
)
from adaptive_document_agent.agent.report_audit_correction import correction_messages
from tests.test_report_audit_scope_v174 import fixture, covered_source


def entity_case():
    result, valid = fixture()
    for page in result.document.pages:
        page.text = page.text.replace('Example Group', 'the Group')
    definition = 'EXAMPLE CORP LTD (the “Company”) and its subsidiaries (together, the “Group”). '
    result.document.pages[3].text = definition + result.document.pages[3].text
    result.observations[0].entity = None
    valid.update(entity='the Group', source_entity='the Group')
    valid['target_quote']['text'] = result.document.pages[0].text
    valid['scope_evidence'][0]['text'] = result.document.pages[3].text
    invalid = deepcopy(valid)
    invalid['entity'] = invalid['source_entity'] = 'EXAMPLE CORP LTD and its subsidiaries (the Group)'
    return result, valid, invalid


def draft(binding):
    return AuditScopeDraft(bindings=[binding], unresolved_observation_ids=['ratio'],
                           unresolved_reason='No exact assurance chain for the percentage.')


def test_assembled_entity_feedback_points_to_retained_identity_contract_not_invalid_alias():
    result, _, invalid = entity_case()
    context = _context(result)
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft(invalid), context)
    issue, = raised.value.issues
    assert issue['field'] == 'entity/source_entity/scope_evidence'
    assert issue['expected'] == dict(retained_target_entity=None, target_entity_locked=False,
        source_identity_must_be_contiguous=True, source_identity_requires_literal_definition=True)
    assert invalid['source_entity'] not in json.dumps(issue['expected'])
    assert 'may be reselected together from the source' in issue['message']


def test_model_reselects_literal_defined_entity_on_second_draft_then_independent_review_passes():
    result, valid, invalid = entity_case()
    original = deepcopy((result.document, result.observations, result.analysis_results))
    class Gateway:
        def __init__(self):
            self.calls, self.drafts = [], 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(schema)
            if schema is AuditScopeDraft:
                self.drafts += 1
                if self.drafts == 1:
                    return draft(invalid)
                feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                contract = next(c for c in feedback['target_contracts'] if c['observation_id']=='amount')
                assert contract['entity_contract']['target_entity_locked'] is False
                assert contract['entity_contract']['retained_target_entity'] is None
                assert 'entity and source_entity are editable proposals' in messages[-1]['content']
                assert 'Do not join a company name' in messages[-1]['content']
                assert self.drafts == 2
                return draft(valid)
            assert schema is AuditScopeReview and self.drafts == 2
            return schema(verdicts=[dict(observation_id='amount', accepted=True,
                covered_source=covered_source(valid), reason='The source definition and covered exact amount support the same Group.')],
                unresolved_accepted=True, unresolved_reason='The percentage has no exact assurance binding.')
    gateway = Gateway()
    review_report_audit_scope(gateway, result)
    require_report_audit_scope(result)
    assert gateway.calls == [AuditScopeDraft, AuditScopeDraft, AuditScopeReview]
    assert (result.document, result.observations, result.analysis_results) == original
    assert result.observations[0].entity is None


def test_existing_target_entity_stays_locked_even_when_another_name_is_literal():
    result, valid, _ = entity_case()
    result.observations[0].entity = 'the Group'
    valid['entity'] = valid['source_entity'] = 'EXAMPLE CORP LTD'
    context = _context(result)
    with pytest.raises(AuditBindingValidationError) as raised:
        _validate(draft(valid), context)
    assert any(issue['field']=='entity' and issue['expected']=='the Group' for issue in raised.value.issues)
    entry = dict(draft=draft(valid).model_dump(mode='json'), error=str(raised.value),
                 validation_issues=raised.value.issues)
    correction_messages(context, draft(valid), entry)
    contract = entry['correction_contracts'][0]['entity_contract']
    assert contract['target_entity_locked'] is True and contract['retained_target_entity']=='the Group'
