"""A misplaced typed proof is relocated unchanged and still needs original-source checks."""
from copy import deepcopy
import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.retained_source_authoring_parallel import OwnedSourcePage
from adaptive_document_agent.agent.retained_page_sources import RetainedPage,validate_authored_pages,AuthoredPageErrors
from adaptive_document_agent.models.executive_brief import BriefQuote
from tests.test_reported_source_context import paraphrased
from adaptive_document_agent.agent import retained_analysis as retained


@pytest.mark.parametrize('with_continuations',[False,True])
def test_root_proofs_move_without_changing_values_or_mutating_input(with_continuations):
    raw=dict(title='A balance',message='The source reports balances.',companion_ids=[],
        context_evidence=[],source_context=[],quote=dict(page=4,text='Original literal proof.'))
    proofs=[raw['quote']]
    if with_continuations:
        proofs.append(dict(page=3,text='Original period and unit header.'))
        raw['continuation_quotes']=[proofs[-1],raw['quote']]
    before=deepcopy(raw)
    page=OwnedSourcePage.model_validate(raw)
    assert raw==before
    assert page.context_evidence==[BriefQuote.model_validate(proof) for proof in proofs]
    dumped=page.model_dump(mode='json')
    assert not {'quote','continuation_quotes'}.intersection(dumped)
    assert dumped['message']==raw['message']
    assert RetainedPage.model_validate(dumped).context_evidence==page.context_evidence


def test_relocated_proof_cannot_approve_a_nonliteral_passage():
    result,selection=paraphrased()
    values=selection.decisions[0].page.model_dump(mode='json')
    values['continuation_quotes']=[dict(page=235,text='An invented quotation absent from the source.')]
    selection.decisions[0].page=OwnedSourcePage.model_validate(values)
    with pytest.raises(AuthoredPageErrors,match='literal quote'):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)


@pytest.mark.parametrize('proof',[None,dict(text='Missing page.'),dict(page=0,text='Invalid page.'),dict(page=1,text='Proof',unexpected='extra')])
def test_bad_proof_does_not_enter_the_page(proof):
    with pytest.raises(ValidationError):
        OwnedSourcePage.model_validate(dict(title='Balance',message='Source balance.',quote=proof))


def test_relocation_never_discards_an_existing_proof_to_fit_capacity():
    existing=[dict(page=i+1,text=f'Original proof {i}.') for i in range(8)]
    with pytest.raises(ValidationError):
        OwnedSourcePage.model_validate(dict(title='Balance',message='Source balance.',context_evidence=existing,
            continuation_quotes=[dict(page=9,text='Another original proof.')]))
