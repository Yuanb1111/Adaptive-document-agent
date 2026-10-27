"""A known failed read retains analysis and cannot spend new report calls."""
import pytest

from adaptive_document_agent.models.coverage import SourceCheck, SourceCoverage, SectionCoverage
from adaptive_document_agent.services.pipeline_completion import is_complete
from tests.test_reporting_checkpoint_v144 import (
    _coverage_fixture, _run_coverage_fixture, SyntheticCoverageFlowClient,
)


@pytest.mark.parametrize('status', ['failed', 'incomplete', 'unchecked'])
def test_public_reporting_retry_stops_before_editorial_work_if_read_still_fails(monkeypatch, status):
    source, raw = _coverage_fixture()
    source.profile.source_coverage = SourceCoverage(
        sections=[SectionCoverage(id='conditions', title='Source conditions', start_page=1, end_page=2)],
        checks=[SourceCheck(section_id='conditions', pages=[1], reason='Verify condition',
            decision_impact='Changes interpretation', status=status, finding='Previous failed read')])
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
    result = _run_coverage_fixture(monkeypatch, source, raw, client)
    assert source == original and result.observations == original.observations
    assert result.analysis_results == original.analysis_results
    assert result.failed_stage == 'source_reading' and result.retry_from == 'reporting'
    assert result.failure_details['component'] == 'SourceReading'
    assert 'Unknown source quote reference' in result.failure_details['message']
    assert result.profile.source_coverage.checks[0].pages == [1]
    assert client.calls == ['SourceCoverageFinding', 'SourceCoverageFinding']
    assert not is_complete(result) and result.executive_brief is None
