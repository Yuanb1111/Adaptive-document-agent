"""Source additions must measure fallback decks and retain late-failure diagnostics."""
from copy import deepcopy
from concurrent.futures import CancelledError
import json

import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent import source_integration_review as integration
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.models import PipelineResult, PresentationTopicSelection
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, PrivacyViolationError
from tests.test_reporting_checkpoint_v142 import _synthetic_checkpoint, SyntheticReportingClient, _gateway
from tests.test_source_integration_v166 import fixture, Gateway


@pytest.mark.parametrize('selection', [None, PresentationTopicSelection()])
def test_reviewed_supplementary_addition_measures_real_native_deck_without_topics(selection):
    result, constraint = fixture()
    result.presentation_topics = selection
    original = deepcopy(result.document)
    reviewer = Gateway(constraint)
    result.executive_brief = integration.review_supplementary_sources(reviewer, result, result.executive_brief)
    assert len(reviewer.calls) == 2
    assert result.executive_brief.items[-1].text == constraint
    deck, counts = budget.measure(result)
    assert counts['total'] == len(deck.slides) > 0 and counts['topic_pages'] == []
    assert constraint in ' '.join(s.text for slide in deck.slides for s in slide.shapes if s.has_text_frame)
    assert result.document == original


class NoTopicsClient(SyntheticReportingClient):
    def generate_structured(self, messages, schema, **kwargs):
        if schema.__name__ == 'PresentationTopicSelection':
            raise LLMResponseError('Synthetic source-row topic selection unavailable')
        return super().generate_structured(messages, schema, **kwargs)


def reporting_run(monkeypatch, *, fault=None):
    source, raw = _synthetic_checkpoint()
    client = NoTopicsClient(source, accept_introduction=True)
    runner = DocumentOrchestrator(_gateway(client))
    monkeypatch.setattr(runner, '_load_document', lambda *a, **kw: source.document)
    measurements, progress = [], []
    measure = budget.measure
    if fault == 'audit_exception':
        from adaptive_document_agent.agent import report_audit_scope
        def broken_gate(*args, **kwargs):
            raise AttributeError('synthetic audit gate defect')
        def broken_refresh(*args, **kwargs):
            monkeypatch.setattr(report_audit_scope, 'require_report_audit_scope', broken_gate)
            broken_gate()
        monkeypatch.setattr(report_audit_scope, 'refresh_report_audit_scope', broken_refresh)

    def source_review(gateway, result, brief, **kwargs):
        # This fixture isolates the orchestration transition after reviewed
        # copy changes. The real two-pass source review is exercised above.
        assert result.presentation_topics is None
        assert result.presentation_plan.planning_origin == 'fallback'
        if fault == 'source_exception':
            raise AttributeError('synthetic source review defect')
        if fault == 'interrupt':
            raise KeyboardInterrupt('synthetic user interruption')
        if fault == 'privacy':
            raise PrivacyViolationError('synthetic privacy rejection')
        if fault == 'cancel':
            raise CancelledError('synthetic cancellation')

        def measured(current):
            if fault == 'measure_exception':
                raise AttributeError('synthetic native measurement defect')
            deck, counts = measure(current)
            measurements.append(counts)
            return deck, counts

        monkeypatch.setattr(budget, 'measure', measured)
        if fault == 'over_budget':
            from adaptive_document_agent.services import slide_budgets
            def reject(deck, current):
                assert measurements and len(deck.slides) > 0
                raise ValueError('Synthetic final physical slide budget exceeded')
            monkeypatch.setattr(slide_budgets, 'require_exported_budgets', reject)
        return brief.model_copy(update={'title': 'Source-reviewed conclusions'})

    monkeypatch.setattr(integration, 'review_supplementary_sources', source_review)
    result = runner.analyse_pdf(raw, resume=source, progress=progress.append)
    return source, result, measurements, progress


def test_full_fallback_reporting_rechecks_changed_brief_without_losing_result(monkeypatch):
    source, result, measurements, _ = reporting_run(monkeypatch)
    assert result.pipeline_state == 'complete' and result.presentation_topics is None
    assert result.executive_brief.title == 'Source-reviewed conclusions'
    assert measurements and measurements[-1]['topic_pages'] == []
    assert result.observations == source.observations
    assert any(w.code == 'presentation_topic_selection_failed' for w in result.validation_warnings)


@pytest.mark.parametrize('fault,stage,error_type', [
    ('over_budget', 'presentation_budget', 'ValueError'),
    ('measure_exception', 'presentation_budget', 'AttributeError'),
    ('source_exception', 'source_integration', 'AttributeError'),
    ('audit_exception', 'report_audit_scope', 'AttributeError'),
])
def test_late_reporting_failure_returns_serializable_partial_checkpoint(monkeypatch, fault, stage, error_type):
    source, result, _, progress = reporting_run(monkeypatch, fault=fault)
    assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    assert result.failed_stage == stage and result.failure_details['error_type'] == error_type
    assert result.observations == source.observations and result.executive_brief
    assert result.llm_usage and result.pipeline_total_ms > 0
    assert any(w.code == 'presentation_topic_selection_failed' for w in result.validation_warnings)
    assert any(w.code.endswith('_failed') and 'Synthetic' in w.message.capitalize()
               for w in result.validation_warnings)
    assert progress[-1] == 'Analysis incomplete; diagnostics and retry checkpoint retained'
    restored = PipelineResult.model_validate_json(result.model_dump_json())
    assert restored.failure_details == result.failure_details
    assert restored.observations == source.observations
    assert restored.validation_warnings == result.validation_warnings
    from adaptive_document_agent.services.pipeline_completion import is_complete
    assert not is_complete(restored)  # A broken review gate must not run again while publishing failure.
    from adaptive_document_agent.ui.analysis_download import render_incomplete
    from tests.test_analysis_export_diagnostics import DownloadUI
    ui = DownloadUI()
    render_incomplete(ui, result, scope_key='late-failure')
    payload = json.loads(ui.downloads['analysis_data.json'])
    assert payload['pipeline_state'] == 'partial' and payload['failed_stage'] == stage
    assert payload['failure_details']['error_type'] == error_type
    assert payload['observations'] and payload['llm_usage']


@pytest.mark.parametrize('fault,error', [('interrupt', KeyboardInterrupt),
    ('privacy', PrivacyViolationError), ('cancel', CancelledError)])
def test_privacy_and_interruption_are_not_converted_to_reporting_fallback(monkeypatch, fault, error):
    with pytest.raises(error, match='synthetic'):
        reporting_run(monkeypatch, fault=fault)
