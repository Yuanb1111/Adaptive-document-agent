"""A similar source passage is correction feedback, never an automatic quote binding."""
import pytest

from adaptive_document_agent.services.literal_quote_feedback import source_passage_hint
from adaptive_document_agent.agent.retained_page_sources import validate_authored_pages,AuthoredPageErrors
from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.models.executive_brief import BriefQuote
from tests.test_reported_source_context import paraphrased


def test_similar_source_paragraph_is_returned_unchanged_without_accepting_the_bad_quote():
    original='Changes in working capital positively affected operating cash flow.'
    wrong='Changes in the working capital positively affected operating cash flow.'
    assert source_passage_hint(wrong,'HEADER\n\n'+original+'\n\nFooter.')==original
    result,selection=paraphrased()
    result.document.pages[-1].text=original
    page=selection.decisions[0].page
    page.source_context=[]
    page.context_evidence=[BriefQuote(page=235,text=wrong)]
    with pytest.raises(AuthoredPageErrors,match='not an accepted quote') as error:
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)
    assert original in str(error.value) and page.context_evidence[0].text==wrong


def test_no_candidate_is_invented_or_truncated_to_fit():
    assert source_passage_hint('A completely different source claim.','Only blank layout here.') is None
    long='Original source words. '*100
    assert source_passage_hint(long,long) is None
