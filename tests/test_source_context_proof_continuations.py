"""Long and cross-page proof remains literal, bounded and subject to review."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
from adaptive_document_agent.agent.retained_page_sources import (
    RetainedPage,AuthoredPageErrors,validate_authored_pages,context_evidence_pages)
from adaptive_document_agent.models import DocumentPage
from adaptive_document_agent.models.executive_brief import BriefQuote
from adaptive_document_agent.services.source_quotes import normalize_quote
from tests.test_reported_source_context import paraphrased
from tests.test_retained_analysis_v216 import gateway


def test_long_proof_splits_losslessly_before_schema_validation_and_keeps_its_page():
    proof='The programme describes delivery risks and management assumptions. '*45
    item=QualifiedSourceCopy.model_validate(dict(scope='FY2023 to FY2025',
        description='describes delivery risks and management assumptions',quote=dict(page=235,text=proof)))
    assert len(item.proof_quotes)>1
    assert all(q.page==235 and len(q.text)<=1800 for q in item.proof_quotes)
    assert normalize_quote(' '.join(q.text for q in item.proof_quotes))==normalize_quote(proof)
    result,selection=paraphrased()
    result.document.pages[-1].text=proof
    page=selection.decisions[0].page
    page.source_context=[item]
    before=deepcopy(page)
    validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)
    assert page==before


def test_cross_page_proof_has_every_footer_page_and_needs_independent_source_review():
    result,selection=paraphrased()
    first='For the reporting periods, delivery delays indicated operational risk.'
    second='Management used budget assumptions and concluded that capacity was sufficient.'
    result.document.pages[-1].text=first
    result.document.pages.append(DocumentPage(page_number=236,text=second))
    result.document.page_count=236
    page=selection.decisions[0].page
    page.source_context=[QualifiedSourceCopy(scope='FY2023 to FY2025',
        description='describes delivery risk alongside management’s assumption-based capacity judgment',
        quote=BriefQuote(page=235,text=first),continuation_quotes=[BriefQuote(page=236,text=second)])]
    context=retained.selection_context(result,source_authoring=True)
    assert context_evidence_pages(page,context,result)=={235,236}
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic selection protocol.')]),result)
    slide=next(s for s in retained.compile_retained_analysis(result).slides if s.slide_type=='analysis')
    assert {235,236}<=set(slide.source_pages)
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    assert not review_complete(result)
    page.source_context[0].continuation_quotes[0].text='A fabricated conclusion about sufficient capacity.'
    with pytest.raises(AuthoredPageErrors,match='literal quote'):
        validate_authored_pages(selection,context,result)


def test_multiple_proofs_keep_existing_capacity_and_cannot_bridge_missing_source_words():
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    item=QualifiedSourceCopy(scope='the programme discussion',description='describes the over-two-year category',
        quote=BriefQuote(page=1,text='The programme considered cases more than'),
        continuation_quotes=[BriefQuote(page=2,text='2 years old under separate conditions.')])
    statement=qualified_source_statement(item)
    assert not reported_source_components('Reported levels. '+statement,item.proof_quotes,declared=[item])[1]
    contexts=[dict(scope='the programme discussion',description='describes delivery risks',
        quote=dict(page=i*4+1,text=f'Original first passage for case {i}.'),
        continuation_quotes=[dict(page=i*4+j+2,text=f'Original continuation passage for case {i} item {j}.')
                             for j in range(3)]) for i in range(5)]
    with pytest.raises(ValidationError,match='16-quotation'):
        RetainedPage(title='Programme',message='Reported levels.',source_context=contexts)


def test_empty_continuations_preserve_existing_serialized_contract():
    item=QualifiedSourceCopy(scope='the programme discussion',description='describes delivery risks',
                             quote=BriefQuote(page=1,text='Original source passage.'))
    assert 'continuation_quotes' not in item.model_dump()


def test_misnested_continuations_move_losslessly_but_unknown_or_conflicting_fields_fail():
    original=dict(scope='the programme discussion',description='describes delivery risks',quote=dict(
        page=1,text='Original first source passage.',continuation_quotes=[dict(page=2,text='Original second source passage.')]))
    before=deepcopy(original)
    item=QualifiedSourceCopy.model_validate(original)
    assert [q.model_dump() for q in item.proof_quotes]==[
        dict(page=1,text='Original first source passage.'),dict(page=2,text='Original second source passage.')]
    assert original==before
    for invalid in [{**original,'continuation_quotes':[dict(page=3,text='A different continuation.')]},
                    {**original,'quote':{**original['quote'],'unknown':'Unrecognized content.'}},
                    {**original,'quote':{**original['quote'],'continuation_quotes':[dict(page=2,text='Short')]}}]:
        with pytest.raises(ValidationError):QualifiedSourceCopy.model_validate(invalid)
