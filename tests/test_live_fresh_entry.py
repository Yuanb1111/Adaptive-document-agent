"""Fresh live-driver entry never loads saved analysis or calls resume twice."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest

from adaptive_document_agent.models import PipelineResult,ParsedDocument,DocumentProfile
from adaptive_document_agent.services.llm import LLMSettings,ProviderName,MockLLMClient
from scripts import run_live_checkpoint as live


def test_fresh_entry_reads_only_original_pdf_and_uses_one_clock(tmp_path,monkeypatch):
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    pdf=tmp_path/'original.pdf';pdf.write_bytes(b'%PDF synthetic test only')
    args=SimpleNamespace(fresh=True,checkpoint=tmp_path/'MUST-NOT-BE-READ.json',pdf=pdf,
        env=Path('unused'),provider='openai',model='gpt-6-luna',output=tmp_path/'run',
        analysis_timeout_seconds=2700,skip_probe=True,export_pptx=False)
    monkeypatch.setattr(live,'settings_for',lambda *a:LLMSettings(provider=ProviderName.MOCK,model='mock'))
    monkeypatch.setattr(live,'create_llm_client',lambda *a:MockLLMClient())
    calls=[]
    def analyse(self,raw,*,resume,progress):
        assert raw==pdf.read_bytes() and resume is None and not self.gateway.cache_enabled
        calls.append(self.gateway.run_deadline)
        return PipelineResult(document=ParsedDocument(document_id='test',sha256=hashlib.sha256(raw).hexdigest(),
            safe_filename='test.pdf',page_count=1),profile=DocumentProfile())
    monkeypatch.setattr(DocumentOrchestrator,'analyse_pdf',analyse)
    monkeypatch.setattr(live,'is_complete',lambda r:False)
    outcome=live.run(args)
    assert len(calls)==1 and calls[0].limit_seconds==2700
    assert outcome['mode']=='live_fresh_pdf' and outcome['checkpoint'] is None
    assert outcome['resume_supplied'] is False and outcome['request_cache_enabled'] is False


@pytest.mark.parametrize('export_finished_at,complete',[(899,True),(901,False)])
def test_fresh_export_cannot_be_reported_complete_after_fifteen_minute_budget(tmp_path,monkeypatch,
                                                                          export_finished_at,complete):
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    from adaptive_document_agent.services.analysis_deadline import AnalysisDeadline
    clock=SimpleNamespace(now=0.)
    deadline=AnalysisDeadline(clock=lambda:clock.now,started_at=0,limit_seconds=900)
    monkeypatch.setattr(live,'AnalysisDeadline',lambda **kw:deadline)
    pdf=tmp_path/'original.pdf';pdf.write_bytes(b'%PDF synthetic test only')
    args=SimpleNamespace(fresh=True,checkpoint=None,pdf=pdf,env=Path('unused'),provider='openai',
        model='gpt-6-luna',output=tmp_path/'run',analysis_timeout_seconds=900,
        skip_probe=True,export_pptx=True)
    monkeypatch.setattr(live,'settings_for',lambda *a:LLMSettings(provider=ProviderName.MOCK,model='mock'))
    monkeypatch.setattr(live,'create_llm_client',lambda *a:MockLLMClient())
    monkeypatch.setattr(DocumentOrchestrator,'analyse_pdf',lambda *a,**kw:PipelineResult(
        document=ParsedDocument(document_id='test',sha256='hash',safe_filename='test.pdf',page_count=1),
        profile=DocumentProfile()))
    monkeypatch.setattr(live,'is_complete',lambda r:True)
    def export(*a):
        clock.now=export_finished_at
        return dict(visual_status='passed',slide_count=1)
    monkeypatch.setattr(live,'export_verified',export)
    outcome=live.run(args)
    assert outcome['complete'] is complete and outcome['limit_includes_pptx_qa']
    if not complete:
        assert outcome['failed_stage']=='pptx_export' and outcome['error_type']=='AnalysisTimeLimitExceeded'
