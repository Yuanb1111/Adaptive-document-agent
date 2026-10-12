"""Known introduction failures retain diagnostics without buying report copy."""
import json
from threading import Event
from concurrent.futures import Future

import pytest

from adaptive_document_agent.agent import company_introduction as introduction
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.export import export_json, export_pptx_with_report
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from tests.test_early_company_introduction import configure_pipeline


@pytest.mark.parametrize('privacy', [False, True])
def test_failure_before_reporting_skips_editorial_work_and_preserves_audit(monkeypatch, privacy):
    completed = Event()
    original_generate = introduction.PreparedCompanyIntroduction._generate
    def generate(self):
        try:
            return original_generate(self)
        finally:
            completed.set()
    monkeypatch.setattr(introduction.PreparedCompanyIntroduction, '_generate', generate)
    def fail(gateway, source, draft, **kwargs):
        source.validation_warnings.append(ValidationIssue(code='company_introduction_summary_audit',
            message='Synthetic rejected source partition', severity='info', stage='presentation'))
        if privacy:
            raise PrivacyViolationError('Local Only')
        raise ValueError('Substantive diagram was classified as layout')
    monkeypatch.setattr(introduction, 'ensure_company_introduction', fail)
    def stage(name, harness):
        if name == 'candidate_scoring':
            assert completed.wait(3)
    harness = configure_pipeline(monkeypatch, on_stage=stage)
    if privacy:
        with pytest.raises(PrivacyViolationError):
            harness.run()
        return
    result = harness.run()
    assert not {'reporting','slide_plan'} & {row['name'] for row in harness.intervals}
    assert result.presentation_plan is None and result.document.pages == harness.source.document.pages
    codes = {w.code for w in result.validation_warnings}
    assert {'company_introduction_summary_audit','company_introduction_unavailable',
            'editorial_stages_skipped'} <= codes
    assert 'company_introduction_duration' in result.stage_details_ms
    assert result.pipeline_total_ms >= result.stage_details_ms['company_introduction_duration']
    assert json.loads(export_json(result))['validation_warnings']
    with pytest.raises(ValueError, match='source-verified opening'):
        export_pptx_with_report(result)
    assert result.presentation_plan is None  # No legacy recovery disguises failure.


def test_known_failure_before_scoring_does_not_purchase_candidate_scores(monkeypatch):
    def prepare(self, gateway, source):
        self._caller = __import__('threading').get_ident()
        self._cancelled = Event()
        self._current = self._source = source
        self._pool = None
        self.duration_ms = 1
        self._future = Future()
        self._future.set_exception(ValueError('Synthetic mandatory introduction failure'))
    monkeypatch.setattr(introduction.PreparedCompanyIntroduction, '__init__', prepare)
    harness = configure_pipeline(monkeypatch)
    result = harness.run()
    assert not {'candidate_scoring','reporting','slide_plan'} & {i['name'] for i in harness.intervals}
    assert not result.candidate_scores and not result.analysis_results
    assert any('candidate scoring' in w.message for w in result.validation_warnings)
