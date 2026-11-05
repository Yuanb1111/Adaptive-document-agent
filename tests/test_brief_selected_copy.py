from adaptive_document_agent.agent.executive_brief import _selected_analysis_copy
from tests.test_retained_analysis_v216 import prepared


def test_brief_receives_complete_selected_copy_without_treating_it_as_evidence():
    result, _ = prepared()
    slide = next(s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    slide.message = 'The measured balance at the final date is unaudited; the earlier date has unknown status.'
    slide.bullets = ['A distinct source-attributed qualification.']
    original = result.model_dump()
    packet = _selected_analysis_copy(result)
    assert packet == [dict(title=slide.title,message=slide.message,bullets=slide.bullets,source_pages=slide.source_pages)]
    assert result.model_dump()==original
    assert not {'evidence','accepted','approved'} & set(packet[0])
    result.presentation_plan = None
    assert _selected_analysis_copy(result)==[]
