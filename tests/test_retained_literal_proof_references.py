import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.retained_literal_proof_references import (
    LiteralProofReference, literal_proof_catalog, rejected_proof_reference_candidates, resolve_literal_proof,
)


def test_catalog_indexes_exact_paragraph_slices_and_emits_compact_metadata():
    text = '  First source paragraph has exact wording.\ncontinued line.\n\nSecond paragraph follows.'
    passages, wire = literal_proof_catalog([dict(page=331, text=text)])

    assert [quote.text for quote in passages.values()] == [
        'First source paragraph has exact wording.\ncontinued line.',
        'Second paragraph follows.',
    ]
    assert all(quote.page == 331 for quote in passages.values())
    assert wire[0] == dict(passage_id=next(iter(passages)), page=331, start=2,
                           end=2 + len(passages[next(iter(passages))].text),
                           first_words='First source paragraph has exact wording. continued line.')
    assert all('text' not in row and len(row['first_words']) < 100 for row in wire)


def test_long_paragraph_is_split_losslessly_into_bounded_exact_page_slices():
    paragraph = ('The source describes changes in working capital and related inventory.\n' * 50).strip()
    passages, wire = literal_proof_catalog([dict(page=8, text=paragraph)])

    quotes = list(passages.values())
    assert len(quotes) > 1
    assert all(8 <= len(quote.text) <= 1800 and quote.page == 8 for quote in quotes)
    from adaptive_document_agent.services.source_quotes import normalize_quote
    assert normalize_quote(' '.join(quote.text for quote in quotes)) == normalize_quote(paragraph)
    assert all(row['end'] - row['start'] == len(quote.text)
               for row, quote in zip(wire, quotes, strict=True))


def test_reference_expansion_is_exact_and_unknown_or_malformed_refs_fail():
    passages, _ = literal_proof_catalog([dict(page=4, text='Changes in working capital were disclosed.')])
    passage_id = next(iter(passages))

    assert resolve_literal_proof(dict(passage_id=passage_id), passages) == {
        'page': 4, 'text': 'Changes in working capital were disclosed.'}
    assert resolve_literal_proof(LiteralProofReference(passage_id=passage_id), passages) == {
        'page': 4, 'text': 'Changes in working capital were disclosed.'}
    with pytest.raises(ValueError, match='Unknown'):
        resolve_literal_proof(dict(passage_id='p4_s0_e99'), passages)
    with pytest.raises(ValueError, match='Malformed'):
        resolve_literal_proof(dict(passage_id=passage_id, text='ignored'), passages)


@pytest.mark.parametrize('repeated',[False,True])
def test_rejected_literal_proof_gets_a_unique_reviewable_reference_without_being_rewritten(repeated):
    from adaptive_document_agent.models.executive_brief import BriefQuote

    source='The filing reports the June balance before describing the later settlement.'
    pages=[dict(page=9,text=source+'\n\n'+source if repeated else source)]
    index,_=literal_proof_catalog(pages)
    quote=BriefQuote(page=9,text=source.replace('June','October'))
    candidates=rejected_proof_reference_candidates([quote],pages,index)
    assert quote.text.endswith('before describing the later settlement.') and 'October' in quote.text
    if repeated:
        assert candidates==[]
    else:
        assert candidates==[dict(rejected_quote_index=1,page=9,passage_id=next(iter(index)))]
        assert resolve_literal_proof(dict(passage_id=candidates[0]['passage_id']),index)['text']==source


def test_legacy_literal_quotes_pass_through_unchanged_for_existing_validators():
    passages, _ = literal_proof_catalog([dict(page=9, text='Changes in working capital were disclosed.')])
    literal = dict(page=9, text='Changes in the working capital were disclosed.')

    assert resolve_literal_proof(literal, passages) is literal


def test_duplicate_source_passages_have_distinct_immutable_references():
    literal = 'The source discusses a repeated passage.'
    passages, wire = literal_proof_catalog([dict(page=12, text=literal + '\n\n' + literal)])

    assert len({quote.text for quote in passages.values()}) == 1
    assert len(passages) == 2
    assert len({row['passage_id'] for row in wire}) == 2


def test_catalog_rejects_invalid_or_duplicate_physical_page_records():
    with pytest.raises(ValueError, match='unique positive'):
        literal_proof_catalog([dict(page=1, text='A valid source passage.'),
                               dict(page=1, text='A duplicate page.')])
    with pytest.raises(ValidationError):
        LiteralProofReference.model_validate(dict(passage_id='p1_s0_e10', extra='rejected'))
