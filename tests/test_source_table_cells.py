import pytest

from adaptive_document_agent.agent.source_table_cells import table_cell_options
from adaptive_document_agent.agent.source_integration_quotes import bind_source_quotes
from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft


def draft(cell='@cell[3:1-1]', quote='@lines[1-2]'):
    return SourceIntegrationDraft(additions=[dict(label='Conditions', text='The source gives conditions.',
        evidence=[dict(page=3, text=quote)], comparison_table=dict(headers=['Condition', 'Scope'],
        rows=[[cell, '@cell[3:2-2]']]))], decisions=[])


def test_literal_cells_bind_from_own_resolved_quotes_without_rewriting_source():
    pages = {3: 'The contract may be cancelled.\nNo compensation is payable.\nOther matters.'}
    original = draft()
    options = table_cell_options(3, pages[3])
    assert dict(ref='@cell[3:1-2]', characters=58) in options
    bound = bind_source_quotes(original, pages)
    assert bound.additions[0].comparison_table.rows == [
        ['The contract may be cancelled.', 'No compensation is payable.']]
    assert original.additions[0].comparison_table.rows[0][0] == '@cell[3:1-1]'
    assert pages[3].endswith('Other matters.')


@pytest.mark.parametrize('cell,quote', [('@cell[4:1-1]', '@lines[1-2]'),
    ('@cell[3:3-3]', '@lines[1-2]'), ('@cell[3:0-1]', '@lines[1-2]'),
    ('@cell[3:1-9]', '@lines[1-2]'), ('@cell[3:no]', '@lines[1-2]'),
    ('@cell[3:1-1]', 'Invented quotation containing the contract.')])
def test_unowned_missing_and_invalid_cell_references_cannot_supply_evidence(cell, quote):
    with pytest.raises(ValueError, match='cell'):
        bind_source_quotes(draft(cell, quote), {3: 'The contract may be cancelled.\nNo compensation is payable.\nOther matters.',
                                               4: 'Unowned source.'})


def test_references_never_allow_overlong_cells_or_accept_a_legacy_cell():
    with pytest.raises(ValueError, match='180'):
        bind_source_quotes(draft(), {3: 'A' * 181 + '\nNo compensation is payable.'})
    legacy = draft('Unverified legacy claim')
    assert bind_source_quotes(legacy, {3: 'The contract may be cancelled.\nNo compensation is payable.'}
        ).additions[0].comparison_table.rows[0][0] == 'Unverified legacy claim'
    # This binder grants no approval; the caller still runs literal-cell and meaning validation.


def test_wire_table_schema_allows_only_premeasured_references_then_binds_base_model():
    import json
    from pydantic import ValidationError
    from adaptive_document_agent.agent.source_table_cells import source_cell_item_schema
    from adaptive_document_agent.agent.source_integration_quotes import numbered_source_pages
    from adaptive_document_agent.agent.prompting import untrusted_document_message
    from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
    pages = {3: 'The contract may be cancelled.\nNo compensation is payable.\nOther matters.'}
    schema = source_cell_item_schema([untrusted_document_message(json.dumps({
        'source_pages': numbered_source_pages([dict(page=3, text=pages[3])])}))])
    value = draft().additions[0].model_dump(mode='json')
    from adaptive_document_agent.agent.source_table_cells import phrase_cell_options
    options = phrase_cell_options(3, pages[3])
    by_text = {o['text']: o['ref'] for o in options}
    value['comparison_table']['rows'] = [[by_text['The contract may be cancelled.'],
                                        by_text['No compensation is payable.']]]
    wire = schema.model_validate(value)
    base = ExecutiveBriefItem.model_validate(wire.model_dump(mode='json'))
    bound = bind_source_quotes(SourceIntegrationDraft(additions=[base], decisions=[]), pages)
    assert bound.additions[0].comparison_table.rows[0][0] == 'The contract may be cancelled.'
    value['comparison_table']['rows'][0][0] = '@cell[3:1-3]'
    with pytest.raises(ValidationError, match='literal_error'):
        schema.model_validate(value)


def test_independent_review_receives_table_conditions_as_published_audience_copy():
    from adaptive_document_agent.agent.source_integration_bindings import merged_review_context
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    item = draft().additions[0]
    bound = bind_source_quotes(draft(), {3: 'The contract may be cancelled.\nNo compensation is payable.'})
    context = merged_review_context({'current_brief': ExecutiveBrief(items=[item]).model_dump()},
        bound, ExecutiveBrief(items=[item, bound.additions[0]]))
    audience = context['merged_brief_items'][1]['audience_text']
    assert 'No compensation is payable.' in audience
    assert 'No compensation is payable.' not in bound.additions[0].text


def test_phrase_choices_keep_line_wrapped_conditions_and_numeric_tokens_continuous():
    from adaptive_document_agent.agent.source_table_cells import phrase_cell_options
    text = ('As of June 30, 2024, no administrative penalty was imposed on us during the\n'
            'Track Record Period; we leased 17 properties totaling 30,937.0 square meters. '
            'The company will consult legal advisors regularly to keep employees informed about applicable laws. ')
    choices = phrase_cell_options(3, text)
    assert all(o['characters'] <= 180 and o['characters'] == len(o['text']) for o in choices)
    assert any('no administrative penalty was imposed on us during the Track Record Period' in o['text']
               for o in choices)
    assert any('June 30, 2024' in o['text'] for o in choices)
    assert any('30,937.0' in o['text'] for o in choices)
    assert not any(o['text'].startswith('937.0') for o in choices)
    for option in choices:
        page, span = option['ref'][8:-1].split(':')
        first, last = map(int, span.split('-'))
        assert option['text'] == ' '.join(text[first:last].split())


@pytest.mark.parametrize('gap', ['', ' Important omitted conditions apply. '])
def test_cell_can_cross_adjacent_quote_chunks_but_never_omitted_source_words(gap):
    from adaptive_document_agent.models.executive_brief import BriefQuote
    first = 'The company stated no penalties'
    last = 'were imposed during the reporting period.'
    source = first + (gap or ' ') + last
    value = draft(f'@phrase[3:0-{len(source)}]').model_copy(deep=True)
    value.additions[0].evidence = [BriefQuote(page=3, text=first), BriefQuote(page=3, text=last)]
    value.additions[0].comparison_table.rows[0][1] = 'no penalties'
    if gap:
        with pytest.raises(ValueError, match='own quoted evidence'):
            bind_source_quotes(value, {3: source})
    else:
        bound = bind_source_quotes(value, {3: source})
        assert bound.additions[0].comparison_table.rows[0][0] == source


def test_selected_phrase_can_bind_its_original_paragraph_on_an_already_owned_page():
    from adaptive_document_agent.agent.source_table_cells import phrase_cell_options
    source = 'The source identifies a contract.\n\nThe contract may be cancelled without compensation.'
    chosen = next(o for o in phrase_cell_options(3, source) if 'without compensation' in o['text'])
    value = draft(chosen['ref'], 'The source identifies a contract.')
    value.additions[0].comparison_table.rows[0][1] = 'without compensation'
    with pytest.raises(ValueError):
        bind_source_quotes(value, {3: source})
    bound = bind_source_quotes(value, {3: source}, selected_phrase_evidence=True)
    assert any(q.text == 'The contract may be cancelled without compensation.'
               for q in bound.additions[0].evidence)
    assert value.additions[0].evidence[0].text == 'The source identifies a contract.'
    assert len(bound.additions[0].evidence) == 2


def test_selected_phrase_evidence_never_exceeds_quote_capacity_or_trusts_fabricated_ownership():
    from adaptive_document_agent.agent.source_table_cells import phrase_cell_options
    from adaptive_document_agent.models.executive_brief import BriefQuote
    source = 'Original ownership evidence.\n\nThe contract may be cancelled without compensation.'
    chosen = next(o for o in phrase_cell_options(3, source) if 'without compensation' in o['text'])
    value = draft(chosen['ref'], 'Original ownership evidence.')
    value.additions[0].comparison_table.rows[0][1] = 'without compensation'
    pages = {3: source}
    for page in range(4, 9):
        text = f'Additional literal source paragraph {page}.'
        value.additions[0].evidence.append(BriefQuote(page=page, text=text))
        pages[page] = text
    with pytest.raises(ValueError):
        bind_source_quotes(value, pages, selected_phrase_evidence=True)
    forged = draft(chosen['ref'], 'Invented ownership evidence.')
    with pytest.raises(ValueError):
        bind_source_quotes(forged, {3: source}, selected_phrase_evidence=True)
