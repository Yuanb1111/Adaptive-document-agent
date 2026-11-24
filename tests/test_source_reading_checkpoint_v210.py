"""A known failed read retains analysis and cannot spend new report calls."""
import pytest

from adaptive_document_agent.models.coverage import SourceCheck, SourceCoverage, SectionCoverage
from adaptive_document_agent.models import PresentationPlan, ValidationIssue
from adaptive_document_agent.services.pipeline_completion import is_complete
from tests.test_reporting_checkpoint_v144 import (
    _coverage_fixture, _run_coverage_fixture, SyntheticCoverageFlowClient,
)


def unfinished_source(status):
    return SourceCoverage(
        sections=[SectionCoverage(id='conditions', title='Source conditions', start_page=1, end_page=2)],
        checks=[SourceCheck(section_id='conditions', pages=[1], reason='Verify condition',
            decision_impact='Changes interpretation', status=status, finding='Previous failed read')])


@pytest.mark.parametrize(('status', 'prior_introduction'), [
    ('failed', None), ('incomplete', 'verified'), ('unchecked', 'unsupported')])
def test_public_reporting_retry_stops_before_editorial_work_if_read_still_fails(
        monkeypatch, status, prior_introduction):
    source, raw = _coverage_fixture()
    source.profile.source_coverage = unfinished_source(status)
    if prior_introduction:
        statement = 'We provide scheduling software for operating teams.'
        source_quote = statement if prior_introduction == 'verified' else 'Unsupported words.'
        source.presentation_plan = PresentationPlan(title='Previous report', company=dict(
            summary_overview=dict(title='Operations', source_section='Summary', items=[
                dict(label='Services', text=statement, source_pages=[2], source_quote=source_quote)])))
        source.validation_warnings.append(ValidationIssue(code='company_introduction_selection_audit',
            stage='presentation',severity='info',message='Previous introduction selection.'))
    original = source.model_copy(deep=True)

    class Client(SyntheticCoverageFlowClient):
        def generate_structured(self, messages, response_model, **kwargs):
            assert response_model.__name__ == 'SourceCoverageFinding', 'Unexpected dependent model call'
            self.calls.append(response_model.__name__)
            return self._typed(response_model, dict(found=True, finding='A claim',
                quotes=[dict(ref='p99_q1')]))

    client = Client(source)
    # The mock adapter uses the runtime wire schema for both reads.
    from adaptive_document_agent.agent.source_coverage import SourceCoverageFinding
    from adaptive_document_agent.agent.source_check_references import reference_schema
    client.additional_schemas['SourceCoverageFinding'] = reference_schema(SourceCoverageFinding)
    result = _run_coverage_fixture(monkeypatch, source, raw, client, background=True)
    assert source == original and result.observations == original.observations
    assert result.analysis_results == original.analysis_results
    assert result.failed_stage == 'source_reading' and result.retry_from == 'reporting'
    assert result.failure_details['component'] == 'SourceReading'
    assert 'Unknown source quote reference' in result.failure_details['message']
    assert result.profile.source_coverage.checks[0].pages == [1]
    assert client.calls == ['SourceCoverageFinding', 'SourceCoverageFinding']
    assert 'company_introduction_duration' not in result.stage_details_ms
    if prior_introduction:
        assert original.validation_warnings[-1] in result.validation_warnings
    if prior_introduction == 'verified':
        assert result.presentation_plan.company == original.presentation_plan.company
        assert not result.presentation_plan.slides
    else:
        assert result.presentation_plan is None
    assert not is_complete(result) and result.executive_brief is None


def test_fresh_incomplete_source_read_keeps_analysis_without_starting_introduction(monkeypatch):
    from tests.test_early_company_introduction import configure_pipeline

    harness = configure_pipeline(monkeypatch)
    harness.source.profile.source_coverage = unfinished_source('failed')
    result = harness.run()
    assert not harness.client.operations
    assert 'candidate_scoring' in {row['name'] for row in harness.intervals}
    assert result.failed_stage == 'source_reading' and result.retry_from == 'reporting'
    assert result.failure_details['source_checks'][0]['pages'] == [1]
    assert not result.presentation_plan
    assert 'company_introduction_duration' not in result.stage_details_ms
