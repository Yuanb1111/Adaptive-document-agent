"""A timeout must not lose completed catalog work or grant a semantic approval."""
import json
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.catalog_timeout_resume import catalog_timeout_reporting
from adaptive_document_agent.agent.retained_analysis_review import needs_catalog_retry
from adaptive_document_agent.models import ChartPlan, Insight, ReportPlan, ValidationIssue
from tests.test_coverage_binding_v166 import fixture


def checkpoint():
    result, lookup, audit = fixture()
    result.failed_stage, result.pipeline_state, result.retry_from = 'analysis_time_limit', 'partial', 'reporting'
    result.report_plan, result.report_markdown = ReportPlan(), '# Source report'
    result.insights = [Insight(id='i', title='Heading', narrative='Source finding', kind='reported_fact')]
    result.charts = [ChartPlan(id='c', title='Trend', chart_type='line', question='What changed?')]
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_coverage_review',
        stage='presentation', message=json.dumps(audit)))
    return result


class ReviewGateway:
    settings = SimpleNamespace(presentation_strategy='full_catalog')
    discovery_workers = 1

    def generate_structured(self, messages, schema, **kwargs):
        assert schema.__name__ == 'TopicEvidenceReview'
        raise RuntimeError('Independent topic review required')


def test_catalog_watchdog_checkpoint_routes_to_existing_topics_and_rechecks_unverified_wording():
    saved = checkpoint()
    assert needs_catalog_retry(saved)
    with pytest.raises(RuntimeError, match='Independent topic review required'):
        catalog_timeout_reporting(saved, saved.model_copy(deep=True), ReviewGateway(), None, None)


@pytest.mark.parametrize('change', ['focus', 'source', 'coverage'])
def test_mismatched_timeout_evidence_cannot_reuse_catalog(change):
    saved = checkpoint()
    current = saved.model_copy(deep=True)
    if change == 'source':
        current.observations[0].raw_value = 'changed'
    if change == 'coverage':
        saved.validation_warnings[-1].message = '{}'
    assert catalog_timeout_reporting(saved, current, ReviewGateway(),
        'different' if change == 'focus' else None, None) is None
