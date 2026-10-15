import pytest

from adaptive_document_agent.ui.processing_progress import ProcessingProgress


class Placeholder:
    def markdown(self, text, **kwargs):
        self.text = text


def test_completed_chunks_drive_progress_without_claiming_export_complete():
    ring = ProcessingProgress(Placeholder())
    ring.update("Understanding selected pages 1-5 (1/4)")
    assert ring.percent == 10
    ring.update("Understood selected pages 6-10 (2/4)")
    assert ring.percent == 27
    ring.update("Understood selected pages 16-20 (4/4)")
    assert ring.percent == 45
    ring.update("Complete")
    assert ring.percent == 90
    ring.update("Rendering and checking PowerPoint layout")
    assert ring.percent == 97
    ring.fail("PowerPoint export blocked")
    assert ring.percent == 97 and ring.state == "error"
    ring.reset()
    assert ring.percent == 0 and ring.state == "running"
    ring.finish()
    assert ring.percent == 100 and ring.state == "complete"


def test_progress_stays_monotonic_and_escapes_untrusted_messages():
    placeholder = Placeholder()
    ring = ProcessingProgress(placeholder)
    ring.update("Planning presentation narrative")
    ring.update("Extracting tables from selected sections")
    assert ring.percent == 85
    ring.update('<img src=x onerror="alert(1)">')
    assert '<img' not in placeholder.text
    assert '&lt;img' in placeholder.text
    assert 'aria-valuenow="85"' in placeholder.text


def test_elapsed_clock_keeps_stage_start_across_polls_and_freezes_on_failure():
    now = [100.0]
    ring = ProcessingProgress(Placeholder(), clock=lambda: now[0])
    now[0] = 105
    ring.update('Understanding document')
    now[0] = 125
    ring.update('Understanding document')
    assert ring.stage_started_at == 105
    assert ring.percent == 4  # Waiting time never advances the percentage.
    ring.update('Selecting presentation questions before chart generation')
    assert ring.stage_started_at == 125
    now[0] = 145
    ring.fail('Analysis stopped')
    snapshot = ring.snapshot()
    now[0] = 999
    restored = ProcessingProgress(Placeholder(), clock=lambda: now[0])
    restored.restore(snapshot)
    assert restored.stopped_at == 145
    assert restored.started_at == 100
    assert restored.stage_started_at == 125
    assert 'fourier-running" aria-hidden' not in restored.placeholder.text


@pytest.mark.parametrize('messages', [
    ['Understanding document', 'Mapping the large document and selecting relevant sections',
     'Understanding selected sections with 4 concurrent requests',
     'Understood selected pages 11-20 (2/5)', 'Understood selected pages 1-10 (3/5)',
     'Checking unselected source sections within the supplementary budget',
     'Merging selected sections into the global document profile'],
    ['Selecting useful analyses', 'Scoring analysis candidates (0/8)',
     'Scoring analysis candidates (2/8)', 'Scoring analysis candidates (8/8)'],
    ['Planning report outline and selecting presentation questions', 'Planning report outline',
     'Selecting presentation questions before chart generation'],
    ['Preparing complete display text for translation',
     'Translating and reviewing display text (0/4 batches complete)',
     'Translating and reviewing display text (1/4; attempt 1)',
     'Translating and reviewing display text (4/4 batches complete)'],
])
def test_batches_parallel_results_and_status_copy_keep_the_large_stage_clock(messages):
    now = [100.0]
    ring = ProcessingProgress(None, clock=lambda: now[0])
    now[0] = 110
    ring.update(messages[0])
    start, identity, sequence = ring.stage_started_at, ring.stage_id, ring.stage_sequence
    for index, message in enumerate(messages[1:], 1):
        now[0] += 7
        ring.update(message)
        assert ring.stage_started_at == start
        assert ring.stage_id == identity and ring.stage_sequence == sequence
        assert ring.label == message
        assert now[0] - ring.stage_started_at == index * 7
    now[0] += 10
    ring.update('Additional status detail (model retry 2)')
    assert ring.stage_started_at == start
    assert ring.stage_id == identity


def test_only_real_phase_boundaries_reset_and_retry_starts_a_new_clock():
    now = [100.0]
    ring = ProcessingProgress(None, clock=lambda: now[0])
    run_id = ring.run_id
    now[0] = 110
    ring.update('Understanding document')
    now[0] = 160
    ring.update('Report requirement: concise English slides')
    assert ring.stage_started_at == 110
    now[0] = 170
    ring.update('Extracting tables from selected sections')
    assert ring.stage_started_at == 170 and ring.stage_id == 'extraction'
    now[0] = 180
    ring.update('Normalizing financial data layer')
    assert ring.stage_started_at == 170
    now[0] = 190
    ring.fail('Analysis stopped')
    assert ring.stage_started_at == 170 and ring.stopped_at == 190
    frozen = ring.snapshot()
    now[0] = 250
    restored = ProcessingProgress(None, clock=lambda: now[0])
    restored.restore(frozen)
    assert restored.run_id == run_id and restored.stage_id == 'extraction'
    assert restored.stage_sequence == ring.stage_sequence
    restored.reset()
    assert restored.run_id != run_id and restored.stage_sequence == 0
    assert restored.started_at == restored.stage_started_at == 250


def test_explicit_phase_identity_is_independent_of_display_wording():
    now = [0.0]
    ring = ProcessingProgress(None, clock=lambda: now[0])
    ring.update('Custom operation batch A', stage_id='custom_operation')
    sequence = ring.stage_sequence
    now[0] = 10
    ring.update('Custom operation batch B', stage_id='custom_operation')
    assert ring.stage_started_at == 0 and ring.stage_sequence == sequence
    ring.update('New phase, same detail', stage_id='other_operation')
    assert ring.stage_started_at == 10 and ring.stage_sequence == sequence + 1


def test_timer_payload_preserves_identity_across_poll_restore_and_terminal_state(monkeypatch):
    from adaptive_document_agent.ui import progress_timer
    payloads = []
    monkeypatch.setattr(progress_timer, 'render', lambda placeholder, data, **kwargs: payloads.append(data))
    now = [100.0]
    ring = ProcessingProgress(Placeholder(), timer=object(), clock=lambda: now[0])
    now[0] = 105
    ring.update('Understanding document')
    now[0] = 125
    ring.update('Understood selected pages 1-5 (1/4)')
    before = payloads[-1]
    assert before['elapsed'] == 25 and before['stage_elapsed'] == 20
    assert before['run_id'] == ring.run_id and before['run_started_at'] == 100
    assert before['stage_id'] == 'discovery'
    saved = ring.snapshot()
    now[0] = 130
    polled = ProcessingProgress(Placeholder(), timer=object(), clock=lambda: now[0])
    polled.restore(saved)
    after = payloads[-1]
    for key in ('run_id', 'run_started_at', 'stage_id', 'stage_sequence'):
        assert before[key] == after[key]
    assert after['elapsed'] == 30 and after['stage_elapsed'] == 25
    polled.finish()
    now[0] = 500
    polled.render()
    assert payloads[-1]['elapsed'] == 30 and payloads[-1]['stage_elapsed'] == 25
    assert payloads[-1]['running'] is False


def test_export_reports_real_stages_and_does_not_finish_before_verification(monkeypatch, tmp_path):
    from tests.test_performance import export_setup, report, LocalRenderStub
    from adaptive_document_agent.services.export import export_pptx_with_report
    export_setup(monkeypatch, tmp_path)
    ring = ProcessingProgress(Placeholder())
    result = export_pptx_with_report(report("# Report"), renderer=LocalRenderStub(), progress=ring.update)
    assert result.payload
    assert ring.percent == 97
    ring.finish()
    assert ring.percent == 100
