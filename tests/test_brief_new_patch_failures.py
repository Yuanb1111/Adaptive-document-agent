"""New failures found in bounded repairs retain a strict path to revalidation."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
from adaptive_document_agent.agent.brief_source_repair import correct_residual_source_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_brief_item_repair import item, audited
from tests.test_brief_targeted_contract_v147 import Replies
from tests.test_executive_brief import result_for


@pytest.mark.parametrize('supported', [True, False])
def test_a_new_invalid_magnitude_declaration_can_only_be_removed_for_an_exact_positive_source(supported):
    source = 'Net cash used was USD70.4 million in 2024.'
    result = result_for([source])
    previous = ExecutiveBriefItem.model_validate(item(source))
    candidate = previous.model_copy(deep=True)
    candidate = ExecutiveBriefItem.model_validate({**candidate.model_dump(),
        'quantity_representations': [dict(quantity_text='USD70.4 million', source_value='-70.4',
            representation='absolute_magnitude')]})
    if not supported:
        result.document.pages[0].text = source.replace('70.4', '(70.4)')
        previous.evidence[0].text = result.document.pages[0].text
        candidate.evidence[0].text = result.document.pages[0].text
    client = Replies([dict(item_0=dict(text=source, remove_quantity_representation_indices=[0]))])
    corrected = correct_residual_source_errors(client, ExecutiveBrief(items=[candidate]), result=result,
        excerpts={1:result.document.pages[0].text}, initial_errors={'item_0':['Meaning review: Attribution.']},
        audit={}, previously_source_valid={0:previous})
    if supported:
        assert corrected and not corrected.items[0].quantity_representations
        assert not validate_executive_brief(corrected, result)
        assert corrected.items[0].text == source and len(client.calls) == 1
    else:
        assert corrected is None


@pytest.mark.parametrize('accept_final', [True, False])
def test_fresh_whole_review_can_reopen_only_its_newly_rejected_item(accept_final):
    source = 'Revenue was 12. Cash was 4.'
    result = result_for([source])
    original = dict(title='Summary', items=[item('Revenue was 12.', label='Revenue'),
                                           item('Cash was 4.', label='Cash')])
    patch = item('The cash balance was 4.', label='Cash')
    patch['evidence'] = deepcopy(original['items'][1]['evidence'])
    replies = Replies([original, dict(item_1=patch), dict(item_0=dict(text='Reported revenue was 12.'))])
    reviewed = []
    def review(brief):
        reviewed.append(deepcopy(brief))
        if brief.items[1].text == 'Cash was 4.':
            return {1:['Clarify the cash finding.']}
        if brief.items[0].text != 'Reported revenue was 12.' or not accept_final:
            return {0:['The updated whole context requires a source-backed qualifier.']}
        return {}
    def run():
        return generate_with_item_repair(replies, [dict(role='system', content='Use only literal source.')],
            result=result, excerpts={1:source}, topics=[],
            source_context={}, semantic_validator=review)
    if accept_final:
        final = run()
        assert final.items[0].text == 'Reported revenue was 12.'
        assert final.items[1].model_dump() == ExecutiveBriefItem.model_validate(patch).model_dump()
        assert not validate_executive_brief(final, result)
    else:
        with pytest.raises(ValueError, match='qualifier'):
            run()
    assert replies.calls[-1][1] == {'item_0'}
    assert audited(result)['post_source_meaning_correction']['locked_indices'] == [1]
    assert original['items'][0]['text'] == 'Revenue was 12.'
