"""Compound headings, candidate starvation and mandatory opening semantics."""
import pytest

from adaptive_document_agent.models import DocumentPage, DocumentProfile, ParsedDocument, PipelineResult, ValidationIssue
from adaptive_document_agent.models.coverage import SourceSection
from adaptive_document_agent.services.company_summary import summary_excerpts, summary_page_numbers, require_verified_introduction
from adaptive_document_agent.services.summary_source import summary_scope
from tests.test_compact_summary_v111 import fixture, Reviewer
from adaptive_document_agent.agent.compact_summary import generate_compact_summary, CompactSummaryReview
from adaptive_document_agent.models.presentation import CompanyProfile


def source():
    document=ParsedDocument(document_id='compound',sha256='synthetic',safe_filename='source.pdf',page_count=180,
        pages=[DocumentPage(page_number=n,text=('SUMMARY AND HIGHLIGHTS\n' if 10<=n<=32 else '')+
               'Cedar designs scheduling software for factory teams.') for n in range(1,181)],
        outline=[SourceSection(id='intro',title='SUMMARY AND HIGHLIGHTS',start_page=10,end_page=32)])
    return PipelineResult(document=document,profile=DocumentProfile(document_summary_pages=list(range(100,150))))


def test_summary_range_survives_distant_discovery_anchor_budget():
    result=source()
    assert summary_page_numbers(result.document)==list(range(10,33))
    assert summary_scope(result,[])==list(range(10,33))
    assert set(range(10,33)) <= {p['page'] for p in summary_excerpts(result.document,result.profile)}


def test_failed_introduction_blocks_export_even_without_custom_requirements():
    result=source()
    result.validation_warnings=[ValidationIssue(code='company_introduction_unavailable',message='Failed',stage='presentation')]
    with pytest.raises(ValueError,match='opening introduction'):
        require_verified_introduction(result)


def test_full_part_ids_cannot_replace_an_accepted_opening_business_introduction():
    result,review,draft=fixture()
    class FinancialOpening(Reviewer):
        def generate_structured(self,messages,schema,**kwargs):
            response=super().generate_structured(messages,schema,**kwargs)
            if schema is CompactSummaryReview:
                response.opening_accepted=False
            return response
    with pytest.raises(ValueError,match='first introductory page'):
        generate_compact_summary(FinancialOpening(draft),result,review,CompanyProfile(summary_review=review))
