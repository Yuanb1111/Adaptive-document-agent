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
