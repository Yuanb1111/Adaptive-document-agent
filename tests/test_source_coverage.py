import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from adaptive_document_agent.agent.source_coverage import check_source_scope, link_coverage, section_ledger
from adaptive_document_agent.models import ParsedDocument, DocumentPage, AnalysisPageRange, Observation, SourceEvidence
from adaptive_document_agent.models.coverage import SourceSection
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.extraction.pdf_parser import PDFParser


def sample():
    document=ParsedDocument(document_id='doc',sha256='abc',safe_filename='doc.pdf',page_count=8,
        pages=[DocumentPage(page_number=n,text=f'Page {n}\nLiteral source condition at {n}.') for n in range(1,9)],
        outline=[SourceSection(id='core',title='Findings',start_page=1,end_page=4),
                 SourceSection(id='conditions',title='Conditions',start_page=5,end_page=8)])
    ranges=[AnalysisPageRange(title='Findings',start_page=1,end_page=3,reason='User question')]
    return document,ranges


def gateway(responses):
    return LLMGateway(MockLLMClient(responses),LLMSettings(provider=ProviderName.MOCK))


def target(start=5,end=6):
    return dict(section_id='conditions',start_page=start,end_page=end,reason='Find condition for the conclusion',decision_impact='Changes applicability')


def test_bounded_source_check_preserves_routes_and_literal_evidence():
    doc,ranges=sample();before=doc.model_dump()
    gw=gateway([dict(targets=[target()],rationale='Potential missing condition'),
        dict(found=True,finding='Condition applies',quotes=[dict(page=5,text='Literal source condition at 5.')])])
    revised,ledger=check_source_scope(doc,ranges,gw)
    assert revised[0]==ranges[0] and (revised[1].start_page,revised[1].end_page)==(5,6)
    assert ledger.calls_used==2 and ledger.checks[0].status=='checked_found'
    assert ledger.checks[0].evidence_quotes=={5:['Literal source condition at 5.']}
    assert not ledger.full_source_review_complete and doc.model_dump()==before
    assert ledger.sections[1].processing_status=='partially_selected'
    assert [u['operation'] for u in gw.usage]==['SourceCoverageSelection','SourceCoverageFinding']


@pytest.mark.parametrize('start,end',[(5,8),(0,5),(6,1000000000),(2,3)])
def test_invalid_target_never_expands_scope(start,end):
    doc,ranges=sample()
    if start==0:start=1  # Out of listed section, valid JSON integer.
    revised,ledger=check_source_scope(doc,ranges,gateway([dict(targets=[target(start,end)],rationale='Check')]))
    assert revised==ranges and ledger.calls_used==1 and not ledger.checks


def test_hallucinated_quote_rejected_without_absence_claim():
    doc,ranges=sample()
    revised,ledger=check_source_scope(doc,ranges,gateway([dict(targets=[target()],rationale='Check'),
        dict(found=True,finding='Found',quotes=[dict(page=5,text='Invented document quote')])]))
    assert revised==ranges and ledger.checks[0].status=='failed'
    assert not ledger.checks[0].evidence_quotes


def test_not_found_means_only_checked_pages_not_source_undisclosed():
    doc,ranges=sample()
    revised,ledger=check_source_scope(doc,ranges,gateway([dict(targets=[target()],rationale='Check'),
        dict(found=False,finding='No requested evidence on these pages',quotes=[])]))
    assert ledger.checks[0].status=='checked_not_found' and ledger.checks[0].pages==[5,6]
    assert len(revised)==2 and not ledger.full_source_review_complete


def test_two_checks_and_selection_are_hard_call_bound():
    doc,ranges=sample();gw=gateway([dict(targets=[target(5,5),target(7,8)],rationale='Check'),
        dict(found=False,finding='Not found on5',quotes=[]),dict(found=False,finding='Not found on7/8',quotes=[])])
    _,ledger=check_source_scope(doc,ranges,gw)
    assert ledger.calls_used==ledger.max_calls==len(gw.client.calls)==3
    assert len({p for c in ledger.checks for p in c.pages})<=6


def test_confirmed_user_scope_never_expanded_or_sent():
    doc,ranges=sample();gw=gateway([])
    revised,ledger=check_source_scope(doc,ranges,gw,confirmed=True)
    assert revised==ranges and not gw.client.calls and ledger.calls_used==0


def test_section_evidence_and_planned_topic_mapping_is_not_export_proof():
    doc,ranges=sample();ledger=section_ledger(doc,ranges)
    obs=Observation(id='fact',metric_original='Value',raw_value='12',value=12,confidence=1,
        evidence=[SourceEvidence(page=2,text='12',extraction_method='digital_text',confidence=1)])
    plan=SimpleNamespace(themes=[SimpleNamespace(id='theme',observation_ids=['fact'])])
    link_coverage(ledger,[obs],plan)
    assert ledger.sections[0].observation_ids==['fact'] and ledger.sections[0].planned_topic_ids==['theme']
    assert ledger.sections[0].export_mapping_status=='not_recorded'


def test_parser_preserves_physical_outline_boundaries():
    import pymupdf
    pdf=pymupdf.open()
    for i in range(5):pdf.new_page().insert_text((30,30),f'Page{i+1}')
    pdf.set_toc([[1,'First',1],[2,'Nested',2],[1,'Second',4]])
    doc=PDFParser().parse(pdf.tobytes(),extract_tables=False);pdf.close()
    assert [(s.title,s.start_page,s.end_page) for s in doc.outline]==[('First',1,3),('Nested',2,3),('Second',4,5)]


def test_gateway_output_limit_reaches_adapter_and_changes_cache_identity(tmp_path):
    from adaptive_document_agent.utils.caching import DiskCache
    from pydantic import BaseModel
    class Answer(BaseModel):
        value: str
    class Client(MockLLMClient):
        caps=[]
        def generate_text(self,messages,**kwargs):
            self.caps.append(kwargs['max_tokens'])
            return super().generate_text(messages,**kwargs)
    client=Client([{'value':'a'},{'value':'b'}]);gw=LLMGateway(client,LLMSettings(provider=ProviderName.MOCK),cache=DiskCache(tmp_path))
    messages=[{'role':'user','content':'fixed request'}]
    assert gw.generate_structured(messages,Answer,stage='discovery',max_tokens=128,allow_repair=False).value=='a'
    assert gw.generate_structured(messages,Answer,stage='discovery',max_tokens=128,allow_repair=False).value=='a'
    assert gw.generate_structured(messages,Answer,stage='discovery',max_tokens=256,allow_repair=False).value=='b'
    assert client.caps==[128,256] and gw.usage[1]['cache_hit']
