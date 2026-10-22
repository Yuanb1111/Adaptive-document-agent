"""Pending source integration is retryable but cannot cross delivery boundaries."""
import pytest

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.models.coverage import SourceCheck, SourceCoverage
from adaptive_document_agent.services.pipeline_completion import is_complete
from tests.test_reporting_checkpoint_v144 import (
    _coverage_fixture, _run_coverage_fixture, SyntheticCoverageFlowClient,
)


@pytest.mark.parametrize('accepted', [False, True])
def test_report_recovery_enters_source_review_and_requires_fresh_acceptance(monkeypatch, accepted):
    source, raw = _coverage_fixture()
    quote = source.document.pages[0].text
    source.profile.source_coverage = SourceCoverage(checks=[SourceCheck(
        section_id='operating_counts', pages=[1], reason='Verify separately dated operating counts.',
        decision_impact='Qualifies the disclosed operating scale.', status='checked_found',
        finding=quote, evidence_quotes={1: [quote]})])
    source.validation_warnings.append(ValidationIssue(code='source_integration_unresolved', stage='report',
        severity='warning', message='{"reason":"Historical source review was truncated."}'))

    class SourceClient(SyntheticCoverageFlowClient):
        def generate_structured(self, messages, response_model, **kwargs):
            name = response_model.__name__
            if name == 'SourceIntegrationDraft':
                self.calls.append(name)
                return self._typed(response_model, dict(additions=[], decisions=[dict(
                    section_id='operating_counts', disposition='covered',
                    reason='The first conclusion retains the exact separately dated counts.',
                    evidence=[dict(page=1, text=quote)], brief_item_indexes=[0])]))
            if name == 'SourceIntegrationReview':
                self.calls.append(name)
                return self._typed(response_model, dict(verdicts=[dict(section_id='operating_counts',
                    accepted=accepted, reason='The source counts are faithfully retained.' if accepted
                    else 'Independent review rejects the proposed source interpretation.')]))
            return super().generate_structured(messages, response_model, **kwargs)

    client = SourceClient(source)
    from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft, SourceIntegrationReview
    client.additional_schemas.update({schema.__name__: schema
        for schema in (SourceIntegrationDraft, SourceIntegrationReview)})
    result = _run_coverage_fixture(monkeypatch, source, raw, client)
    assert client.calls.count('SourceIntegrationReview') == (1 if accepted else 2)
    assert result.observations == source.observations
    assert result.analysis_results == source.analysis_results
    assert is_complete(result) is accepted
    if accepted:
        assert result.pipeline_state == 'complete' and result.failed_stage is None
    else:
        assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
        assert result.failed_stage == 'source_integration'
        assert result.failure_details['component'] == 'SourceIntegration'
        assert any(issue.code == 'source_integration_unresolved' for issue in result.validation_warnings)


def test_cached_complete_flag_cannot_bypass_source_review_at_native_export(monkeypatch):
    from adaptive_document_agent.services import company_summary, pptx_export
    from tests.test_source_integration_v166 import fixture
    result, _ = fixture()
    assert result.pipeline_state == 'complete'
    # This fixture isolates source integration from the unrelated opening check.
    monkeypatch.setattr(company_summary, 'require_verified_introduction', lambda result: None)
    monkeypatch.setattr(pptx_export, '_compose_presentation',
        lambda *args, **kwargs: pytest.fail('An unreviewed source reached native delivery composition.'))
    with pytest.raises(ValueError, match='Supplementary source integration review'):
        pptx_export.build_presentation(result)


def test_native_export_rechecks_review_after_cached_context_preparation(monkeypatch):
    from adaptive_document_agent.agent.source_integration_review import review_supplementary_sources
    from adaptive_document_agent.services import company_summary, pptx_export
    from tests.test_source_integration_v166 import Gateway, fixture
    result, constraint = fixture()
    result.executive_brief = review_supplementary_sources(Gateway(constraint), result, result.executive_brief)
    assert is_complete(result)
    monkeypatch.setattr(company_summary, 'require_verified_introduction', lambda result: None)
    def compose(changing_result, *args, **kwargs):
        changing_result.profile.analysis_focus = 'A different analytical focus'
        return object()
    monkeypatch.setattr(pptx_export, '_compose_presentation', compose)
    with pytest.raises(ValueError, match='Supplementary source integration review'):
        pptx_export.build_presentation(result)
