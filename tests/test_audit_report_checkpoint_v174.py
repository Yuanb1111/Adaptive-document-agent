"""Full reporting retry transports only the latest audit checkpoint for revalidation."""
import pytest

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.agent import report_audit_scope
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from tests.test_reporting_checkpoint_v142 import _synthetic_checkpoint, _gateway, SyntheticReportingClient


@pytest.mark.parametrize('latest_code', ['report_audit_scope_review', 'report_audit_scope_unresolved'])
def test_reporting_retry_preserves_latest_audit_event_until_source_revalidation(monkeypatch, latest_code):
    source, raw = _synthetic_checkpoint()
    old = ValidationIssue(code='report_audit_scope_review', severity='info', stage='report',
                          message='An obsolete audit checkpoint must not replace the latest one.')
    latest = ValidationIssue(code=latest_code, severity='info', stage='report',
                             message='Latest exact checkpoint for subsequent source revalidation.')
    source.validation_warnings.extend([old, latest])
    original = source.model_copy(deep=True)
    actual = report_audit_scope.refresh_report_audit_scope
    seen = []
    def inspect(gateway, result, **kwargs):
        events = [w for w in result.validation_warnings if w.code in {
            'report_audit_scope_review', 'report_audit_scope_unresolved'}]
        assert events == [latest]
        seen.append(True)
        return actual(gateway, result, **kwargs)
    monkeypatch.setattr(report_audit_scope, 'refresh_report_audit_scope', inspect)
    runner = DocumentOrchestrator(_gateway(SyntheticReportingClient(source, accept_introduction=True)))
    monkeypatch.setattr(runner, '_load_document', lambda data, digest: source.document)
    result = runner.analyse_pdf(raw, resume=source)
    assert seen and result.pipeline_state == 'complete'
    assert source == original
