from adaptive_document_agent.services.export_diagnostics import export_diagnostics
from adaptive_document_agent.services.presentation_visual_qa import VisualQAReport
from tests.test_pptx_export import _result


def test_export_diagnostics_use_verified_physical_count_and_label_planned_count():
    result=_result()
    original=export_diagnostics(result)
    assert original['physical_slides'] is None and original['planned_slides']==original['total_slides']
    report=export_diagnostics(result,visual_report=VisualQAReport(status='passed',slide_count=18))
    assert report['total_slides']==report['physical_slides']==18
    assert report['planned_slides']==original['planned_slides']
