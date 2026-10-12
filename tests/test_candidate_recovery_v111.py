"""Transient failure recovery, bounded scoring and presentation-only instructions."""
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
from adaptive_document_agent.services.llm.exceptions import LLMTransportError
from adaptive_document_agent.models.customization import ReportRequirements, ReportRequirement
from adaptive_document_agent.agent.value_scorer import AnalysisValueScorer, SemanticCandidateScores
from tests.test_candidate_scoring_compaction import scoring_fixture


@pytest.mark.parametrize('status',[408,429,500,502,503,504])
def test_one_retry_recovers_server_failure_and_records_both_attempts(monkeypatch,status):
    error=type('InternalServerError',(Exception,),{'status_code':status})('server failed')
    complete=Mock(side_effect=[error,SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='ok'),finish_reason='stop')],usage=None)])
    monkeypatch.setitem(sys.modules,'litellm',SimpleNamespace(completion=complete))
    monkeypatch.setattr('adaptive_document_agent.services.llm.litellm_provider.time.sleep',lambda _:None)
    p=LiteLLMProvider(LLMSettings(provider=ProviderName.OLLAMA,model='fixture'))
    value=p.generate_text([])
    assert value.text=='ok' and complete.call_count==2
    assert [a['status'] for a in value.attempts]==['failed','success']
    assert value.attempts[1]['kind']=='network_retry'
    assert complete.call_args.kwargs['num_retries']==0


@pytest.mark.parametrize('status',[400,401,403,404,422,501])
def test_input_authentication_and_unsupported_errors_never_retry(status):
    error=type('InternalServerError',(Exception,),{'status_code':status})()
    assert not LiteLLMProvider._transient_failure(error)


def test_repeated_internal_server_error_stops_after_two_attempts(monkeypatch):
    error=type('InternalServerError',(Exception,),{})('server failed')
    complete=Mock(side_effect=error)
    monkeypatch.setitem(sys.modules,'litellm',SimpleNamespace(completion=complete))
    monkeypatch.setattr('adaptive_document_agent.services.llm.litellm_provider.time.sleep',lambda _:None)
    p=LiteLLMProvider(LLMSettings(provider=ProviderName.OLLAMA,model='fixture'))
    with pytest.raises(LLMTransportError) as e:p.generate_text([])
    assert complete.call_count==2 and len(e.value.attempts)==2


def test_parallel_scoring_retains_source_order_and_caller_progress():
    candidates,_,profile,_,_=scoring_fixture(80)
    barrier=Barrier(2)
    class Client:
        discovery_workers=2
        def generate_structured(self,messages,response_model,**kwargs):
            import ast
            ids=ast.literal_eval(messages[-1]['content'].split(': ',1)[1])
            barrier.wait(timeout=3)
            return SemanticCandidateScores(scores=[dict(candidate_id=i,score=.8,rejected=False,reasons=['Supported comparison.']) for i in ids])
    progress=[]
    batches,audits=AnalysisValueScorer(Client())._semantic_batches(candidates,profile,progress=progress.append)
    assert [i for ids,_ in batches for i in ids]==[c.id for c in candidates]
    assert len(audits)==2 and progress==['Scoring analysis candidates (0/2)','Scoring analysis candidates (1/2)','Scoring analysis candidates (2/2)']


def test_scoring_reduces_verified_deepseek_reasoning_and_caps_output():
    p=request_reasoning_policy(LLMSettings(),stage='planner',operation='SemanticCandidateScores',model='deepseek-flash')
    assert p['options']=={'extra_body':{'thinking':{'type':'disabled'}}}
    assert p['output_token_limit']==6000
    assert request_reasoning_policy(LLMSettings(),stage='presentation',operation='SummaryReadBatch',model='deepseek-flash')['output_token_limit']==12000


def test_only_analytical_focus_reaches_scoring_and_full_requirements_stay_in_result():
    from adaptive_document_agent.agent.report_requirements import instruction_messages
    _,_,profile,_,_=scoring_fixture(1)
    profile.report_requirements=ReportRequirements(original_request='中文正文；全部表格；重点现金流',items=[
        ReportRequirement(id='lang',kind='output_language',request_quote='中文正文',description='Chinese body',language='Chinese'),
        ReportRequirement(id='detail',kind='content_detail',request_quote='全部表格',description='Complete appendix'),
        ReportRequirement(id='focus',kind='analysis_focus',request_quote='重点现金流',description='Cash flow focus')])
    messages=instruction_messages(profile,purpose='analysis prioritization')
    assert '重点现金流' in messages[0]['content'] and '中文正文' not in messages[0]['content'] and '全部表格' not in messages[0]['content']
    assert len(profile.report_requirements.items)==3


def test_real_adapter_applies_scoring_output_cap_through_gateway(monkeypatch):
    from pydantic import SecretStr
    provider=LiteLLMProvider(LLMSettings(api_key=SecretStr('mock-only')))
    complete=Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"scores":[]}'),finish_reason='stop')],usage=None))
    monkeypatch.setattr(provider,'_completion',complete)
    LLMGateway(provider,provider.settings).generate_structured([],SemanticCandidateScores,stage='planner')
    assert complete.call_args.kwargs['max_tokens']==6000
    assert complete.call_args.kwargs['extra_body']=={'thinking':{'type':'disabled'}}


def test_summary_server_retry_reaches_complete_compact_introduction(monkeypatch):
    """A transient reading failure must recover through the real gateway path."""
    import json
    from tests.test_compact_summary_v111 import fixture
    from adaptive_document_agent.agent.summary_presentation import generate_summary_presentation
    from adaptive_document_agent.models.presentation import CompanyProfile
    from adaptive_document_agent.services.summary_validation import presentation_errors
    result, _, draft = fixture()
    attempted = []
    error = type('InternalServerError', (Exception,), {'status_code':500})('server failed')

    def complete(messages, **kwargs):
        schema = json.loads(next(m['content'].split(': ',1)[1] for m in messages
            if m['content'].startswith('Return only valid JSON matching this schema: ')))
        name = schema['title']
        attempted.append(name)
        if name == 'SummaryReadBatch':
            if attempted.count(name) == 1:
                raise error
            content=next(m['content'] for m in messages if m['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>'))
            data = json.loads(content.split('\n',1)[1].rsplit('\n',1)[0])
            parts = [dict(block_id=b['block_id'],start_line=n,end_line=n,
                title='Scheduling',role='content',reading_note='Staff training is required.',
                facts=[dict(label='Scheduling',text=line.strip(),quote_start_line=n,quote_end_line=n)])
                for b in data for n,line in b['lines']]
            response = {'parts':parts}
        elif name == 'CompactSummaryDraft':
            response = draft
        elif name == 'CompactSummaryReview':
            content=next(m['content'] for m in messages if m['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>'))
            data = json.loads(content.split('\n',1)[1].rsplit('\n',1)[0])
            response = {'parts':[dict(part_id=p['id'],accepted=True,
                reason='The fixture retains the source training requirement.') for p in data['source']['parts']]}
        else:
            raise AssertionError(name)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(response)),finish_reason='stop')],usage=None)

    settings = LLMSettings(provider=ProviderName.OLLAMA,model='fixture')
    provider = LiteLLMProvider(settings)
    monkeypatch.setitem(sys.modules,'litellm',SimpleNamespace(completion=complete))
    monkeypatch.setattr('adaptive_document_agent.services.llm.litellm_provider.time.sleep',lambda _:None)
    gateway = LLMGateway(provider,settings)
    from adaptive_document_agent.models.summary import SummaryPageRange
    company = generate_summary_presentation(gateway,result,[1],CompanyProfile,
        scope_ranges=[SummaryPageRange(start_page=1,end_page=1,reason='Complete introductory source.')])
    assert company.summary_review.status=='complete' and len(company.summary_pages)==5
    assert len(company.summary_review.parts)==70
    assert not presentation_errors(company.summary_review,company.summary_pages,result)
    assert attempted==['SummaryReadBatch','SummaryReadBatch','CompactSummaryDraft','CompactSummaryReview']
    assert [a['status'] for a in gateway.usage[0]['attempts']]==['failed','success']
