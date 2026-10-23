"""Late report stages must not inherit a preceding stage's elapsed clock."""
import pytest

from adaptive_document_agent.ui.processing_progress import ProcessingProgress
from adaptive_document_agent.agent.report_audit_scope import review_report_audit_scope
from adaptive_document_agent.agent.source_integration_review import review_supplementary_sources
from tests.test_report_audit_batches_v174 import BatchGateway, many_targets
from tests.test_source_integration_v166 import Gateway, fixture


@pytest.mark.parametrize('messages,identity', [
    (['Reviewing source audit qualifications',
      'Locating additional source pages for exact audit qualifications',
      'Audit qualification source group 1/2', 'Linking audit qualifications: reviewing 3 measures',
      'Audit qualification: splitting 3 measures after proven output truncation',
      'Audit qualification: reusing 2 independently reviewed measures'], 'report_audit_scope'),
    (['Reviewing supplementary sources against the final conclusions'], 'source_integration'),
    (['Writing the evidence-bound executive briefing'], 'executive_briefing'),
    (['Checking requested report customizations', 'Verifying requested report coverage'], 'requirements_review'),
    (['Preparing complete display text for translation',
      'Translating and reviewing display text (1/4; attempt 1)'], 'localization'),
])
def test_late_stage_resets_once_and_survives_poll_retry_and_failure(messages, identity):
    now = [100.0]
    ring = ProcessingProgress(None, clock=lambda: now[0])
    ring.update('Planning presentation narrative')
    now[0] = 620
    ring.update(messages[0])
    assert ring.stage_id == identity and ring.stage_started_at == 620
    sequence = ring.stage_sequence
    for message in [*messages, 'Additional status detail (model retry 2)']:
        now[0] += 10
        ring.update(message)
        assert ring.stage_started_at == 620 and ring.stage_sequence == sequence
    restored = ProcessingProgress(None, clock=lambda: now[0])
    restored.restore(ring.snapshot())
    assert restored.started_at == 100 and restored.stage_started_at == 620
    assert restored.percent == ring.percent == (90 if identity in {'requirements_review', 'localization'} else 85)
    restored.fail('Analysis stopped')
    stopped = restored.stopped_at
    now[0] += 100
    assert restored.stopped_at == stopped and restored.stage_started_at == 620


def test_real_audit_and_source_callbacks_reset_the_clock_at_entry():
    now = [100.0]
    ring = ProcessingProgress(None, clock=lambda: now[0])
    ring.update('Planning presentation narrative')
    result, binding = many_targets(3)
    now[0] = 360
    review_report_audit_scope(BatchGateway(binding), result, progress=ring.update)
    assert ring.stage_id == 'report_audit_scope' and ring.stage_started_at == 360
    now[0] = 500
    ring.update('Refining analytical priorities using actual physical slide costs')
    now[0] = 620
    result, constraint = fixture()
    review_supplementary_sources(Gateway(constraint), result, result.executive_brief, progress=ring.update)
    assert ring.stage_id == 'source_integration' and ring.stage_started_at == 620
    now[0] = 780
    assert now[0] - ring.stage_started_at == 160  # Not 520 seconds from the previous work.
