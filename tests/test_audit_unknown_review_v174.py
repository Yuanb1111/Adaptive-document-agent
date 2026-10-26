"""Fresh independent unknown review is mandatory for every report completion path."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_batches import resumable_batches
from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _review_batch, require_report_audit_scope,
    review_report_audit_scope, reviewed_audit_bindings,
)
from adaptive_document_agent.services import company_summary, pipeline_completion, pptx_export
from tests.test_audit_review_contract_v174 import ScriptedGateway, unknown_draft
from tests.test_report_audit_scope_v174 import covered_source, fixture, Gateway


@pytest.mark.parametrize('mutation', ['old_contract', 'missing_contract', 'old_strategy'])
def test_old_review_cannot_complete_export_or_resume_and_is_reaudited(monkeypatch, mutation):
    result, binding = fixture()
    review_report_audit_scope(Gateway(binding), result)
    original = deepcopy((result.observations, result.document))
    audit = json.loads(result.validation_warnings[-1].message)
    if mutation == 'old_contract':
        audit['contract'] = 'report-audit-scope-v174-batched'
    elif mutation == 'missing_contract':
        audit.pop('contract')
    else:
        audit['request_strategy'] = 'audit-scope-covered-counterparts-v174'
    result.validation_warnings[-1].message = json.dumps(audit)
    old_issue = result.validation_warnings[-1].model_copy(deep=True)
    assert not reviewed_audit_bindings(result)
    with pytest.raises(ValueError, match='unfinished or stale'):
        require_report_audit_scope(result)
    result.pipeline_state = 'complete'
    monkeypatch.setattr(pipeline_completion, 'source_review_complete', lambda _: True)
    monkeypatch.setattr(pipeline_completion, 'topic_coverage_complete', lambda _: True)
    assert not pipeline_completion.is_complete(result)
    monkeypatch.setattr(company_summary, 'require_verified_introduction', lambda _: None)
    monkeypatch.setattr(pptx_export, '_compose_presentation',
                        lambda *a, **k: pytest.fail('Stale audit must fail before composing slides.'))
    with pytest.raises(ValueError, match='unfinished or stale'):
        pptx_export.build_presentation(result)
    failed = result.model_copy(deep=True)
    failed.validation_warnings[-1].code = 'report_audit_scope_unresolved'
    assert resumable_batches(failed, audit['context']) == {}
    gateway = Gateway(binding)
    review_report_audit_scope(gateway, result)
    assert len(gateway.calls) == 2
    assert result.validation_warnings[-2] == old_issue
    require_report_audit_scope(result)
    assert pipeline_completion.is_complete(result)
    assert (result.observations, result.document) == original


def test_unknown_with_exact_covered_counterpart_requires_writer_correction_and_fresh_proof():
    result, binding = fixture()
    rejected = AuditScopeReview(verdicts=[], unresolved_accepted=False,
        unresolved_reason='amount has an exact Revenue row, header and unit on covered page 5. '
                          'Its summary being outside the covered range does not justify unknown.')
    corrected = AuditScopeDraft(bindings=[binding], unresolved_observation_ids=['ratio'],
        unresolved_reason='The ratio cannot inherit amount assurance.')
    accepted = AuditScopeReview(verdicts=[dict(observation_id='amount', accepted=True,
        reason='The exact row and column have covered source proof.', covered_source=covered_source(binding))],
        unresolved_accepted=True, unresolved_reason='The unsupported ratio remains unknown.')
    gateway = ScriptedGateway([unknown_draft(), rejected, corrected, accepted])
    record = dict(attempts=[])
    _review_batch(gateway, _context(result), record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft, AuditScopeReview] * 2
    assert record['corrections_used'] == dict(draft_output=0, binding_validation=0, independent_review=1, review_output=0)
    assert record['draft'] == corrected.model_dump()
    instructions = gateway.calls[1][0][0]['content']
    assert 'BOTH audited and unaudited' in instructions
    assert 'own table and period column' in instructions
    assert 'does NOT prevent a binding' in instructions
    assert gateway.calls[1][0][1] == gateway.calls[3][0][1]
