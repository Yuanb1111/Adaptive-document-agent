"""Budget assurance failures keep their original reporting stage and cause."""
import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.llm.exceptions import LLMTransportError
from tests.test_reporting_checkpoint_v142 import (
    _synthetic_checkpoint, _gateway, SyntheticReportingClient,
)


@pytest.mark.parametrize('error_type', [ValueError, LLMTransportError])
def test_budget_audit_failure_remains_a_reporting_checkpoint_with_original_cause(monkeypatch, error_type):
    source, raw = _synthetic_checkpoint()
    original = source.model_copy(deep=True)
    failure = error_type('Exact final measure assurance could not be reviewed.')
    diagnostic = ValidationIssue(code='report_audit_scope_unresolved', severity='warning',
        stage='report', message='Retained candidate audit checkpoint.')

    def fail_audit(gateway, result, **kwargs):
        result.validation_warnings.append(diagnostic)
        raise budget.FinalBudgetAuditError(failure) from failure

    monkeypatch.setattr(budget, 'refine_presentation_budget', fail_audit)
    runner = DocumentOrchestrator(_gateway(SyntheticReportingClient(source, accept_introduction=True)))
    monkeypatch.setattr(runner, '_load_document', lambda data, digest: source.document)
    result = runner.analyse_pdf(raw, resume=source)

    assert result.pipeline_state == 'partial'
    assert result.retry_from == 'reporting'
    assert result.failed_stage == 'report_audit_scope'
    assert result.failure_details == dict(component='ReportAuditScope',
        error_type=error_type.__name__, message=str(failure))
    assert diagnostic in result.validation_warnings
    assert result.validation_warnings[-1].code == 'report_audit_scope_failed'
    assert source == original
