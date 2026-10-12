"""Independent localization batches overlap without mutating accepted copies."""
from threading import Barrier,get_ident
from types import SimpleNamespace

from adaptive_document_agent.agent.report_localization import prepare_report_language
from adaptive_document_agent.models.customization import ReportRequirements,ReportRequirement
from tests.test_report_customization import table_result


def test_parallel_translation_merges_complete_ids_and_batch_times_on_owner(monkeypatch):
    result=table_result()
    result.profile.report_requirements=ReportRequirements(items=[ReportRequirement(
        id='language',kind='output_language',request_quote='正文中文',description='Chinese prose',language='Chinese')])
    strings=[f'Claim {i}' for i in range(96)]
    from adaptive_document_agent.services import pptx_export,report_language,localized_summary_copy
    monkeypatch.setattr(pptx_export,'presentation_for_copy',lambda _:SimpleNamespace())
    monkeypatch.setattr(report_language,'audience_copy',lambda _:strings)
    monkeypatch.setattr(report_language,'copy_limits',lambda _:{s:100 for s in strings})
    monkeypatch.setattr(report_language,'copy_fit_errors',lambda *_:[])
    monkeypatch.setattr(localized_summary_copy,'summary_copy_units',lambda _:[])
    barrier=Barrier(2);owner=get_ident();threads=[]
    from adaptive_document_agent.agent import report_localization
    def translate(gateway,batch,language,presentation,*,failures,timings):
        threads.append(get_ident());barrier.wait(timeout=3)
        timings['localization_translation_requests']=7
        return {row['text']:'中文'+str(row['id']) for row in batch},[],{'ids':[row['id'] for row in batch]}
    monkeypatch.setattr(report_localization,'_translate_batch',translate)
    updates=[]
    prepare_report_language(SimpleNamespace(discovery_workers=2),result,progress=lambda p:updates.append((get_ident(),p)))
    assert len(result.profile.report_requirements.copy_translations)==96
    assert len(set(threads))==2 and owner not in threads
    assert all(t==owner for t,_ in updates)
    assert result.stage_details_ms['localization_translation_requests']==14
    assert '2/2 batches complete' in updates[-1][1]
