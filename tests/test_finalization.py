import json
import pytest
from adaptive_document_agent.services import finalization as editing
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.models import PresentationTheme
from tests.test_p1_theme_planning import themed_result


def response(result,**change):
    slide=next(s for s in result.presentation_plan.slides if s.theme_id=='operations')
    edit=dict(slide_id=slide.id,title=slide.title,message=slide.message,bullets=slide.bullets)
    edit.update(change)
    return dict(edits=[edit])


def gateway(payload):
    return LLMGateway(MockLLMClient([payload]),LLMSettings(provider=ProviderName.MOCK))


def test_single_topic_revision_changes_only_target_and_preserves_original():
    result=themed_result();original=result.model_dump()
    gw=gateway(response(result,message='Operating activity and service requirements'))
    draft=editing.revise_topic(result,'operations','Shorten this explanation','concise',gw)
    assert result.model_dump()==original and editing.fact_hash(result)==editing.fact_hash(draft)
    original_slides={s.id:s for s in result.presentation_plan.slides}
    for slide in draft.presentation_plan.slides:
        if slide.theme_id!='operations':assert slide==original_slides[slide.id]
    assert len(gw.client.calls)==1 and len(draft.finalization['revisions'])==1
    assert draft.finalization['revisions'][0]['evidence']['source_pages']==[3]
    assert draft.finalization['revisions'][0]['changes'][0]['diff']


def test_locked_theme_does_not_make_a_model_call():
    result=editing.set_locks(themed_result(),['operations']);gw=gateway({})
    with pytest.raises(ValueError,match='Unlock'):editing.revise_topic(result,'operations','Shorten','concise',gw)
    assert not gw.client.calls


def test_facts_and_locked_text_cannot_change_silently():
    draft=editing.set_locks(themed_result(),['operations'])
    modified=draft.model_copy(deep=True);modified.observations[0].value=999999
    with pytest.raises(ValueError,match='source facts'):editing.assert_stable(modified)
    modified=draft.model_copy(deep=True)
    next(s for s in modified.presentation_plan.slides if s.theme_id=='operations').title='Altered'
    with pytest.raises(ValueError,match='Locked theme'):editing.assert_stable(modified)


@pytest.mark.parametrize('change',[dict(title='Invented 999999 profit'),dict(slide_id='other-slide')])
def test_invalid_model_revision_is_atomic(change):
    result=themed_result();before=result.model_dump();gw=gateway(response(result,**change))
    with pytest.raises(ValueError):editing.revise_topic(result,'operations','Change this','balanced',gw)
    assert result.model_dump()==before


def test_order_requires_complete_unique_theme_set():
    result=themed_result();before=result.model_dump()
    with pytest.raises(ValueError,match='exactly once'):editing.reorder(result,[])
    with pytest.raises(ValueError,match='exactly once'):editing.reorder(result,['operations','operations'])
    assert result.model_dump()==before


def test_export_finalization_disables_repair_and_checks_locks(monkeypatch,local_render_stub):
    from adaptive_document_agent.services import export
    from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa
    draft=editing.set_locks(themed_result(),['operations']);modes=[]
    def qa(result,auto_repair=True):
        modes.append(auto_repair);return run_comprehensive_qa(result,auto_repair=auto_repair)
    monkeypatch.setattr('adaptive_document_agent.services.qa_reporter.run_comprehensive_qa',qa)
    export.export_pptx(draft)
    assert modes==[False];editing.assert_stable(draft)


def test_stable_noop_reorder_keeps_locked_content():
    result=editing.set_locks(themed_result(),['operations']);before=editing.theme_hash(result,'operations')
    draft=editing.reorder(result,['operations'])
    assert editing.theme_hash(draft,'operations')==before
    assert draft.finalization['revisions'][-1]['operation']=='reorder'
