"""The joined text bound applies to complete author-supplied alternatives."""
import json

import pytest

from adaptive_document_agent.agent.source_integration_copy import shorten_additions
from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_budget_output_v145 import gateway, response
from tests.test_source_completion_capacity_v173 import _outputs


def boundary_clauses(last_size=157):
    # The separators count, and the first sentence is longer than one third of a slot.
    return ['A' * 220 + '.', 'B' * 169 + '.', 'C' * (last_size - 1) + '.']


def copy_request(outputs):
    draft, _ = _outputs('The purchaser may cancel the contract without compensation.')
    draft.additions.append(draft.additions[0].model_copy(update={'label': 'Reopened terms'}, deep=True))
    draft.decisions[0].brief_item_indexes = [5, 6]
    raw = draft.model_dump(mode='json')
    raw['additions'][1]['text'] *= 20
    errors = [dict(loc=['additions', 1, 'text'], ctx=dict(max_length=550))]
    llm, _ = gateway(outputs)
    revised = shorten_additions(llm, [], SourceIntegrationDraft, (raw, errors), {}, 5,
                                sentence_compress=True)
    return revised, draft, len(llm.usage)


@pytest.mark.parametrize('authoring', ['both_fit', 'only_complete_fits', 'only_concise_fits', 'bare_array'])
def test_preserves_a_whole_fitting_authored_version_and_all_other_fields(authoring):
    fitting = boundary_clauses()
    overflow = boundary_clauses(158)
    assert len(' '.join(fitting)) == 550
    assert len(' '.join(overflow)) == 551
    variants = {
        'both_fit': dict(complete=fitting, concise=['A shorter alternative.']),
        'only_complete_fits': dict(complete=fitting, concise=overflow),
        'only_concise_fits': dict(complete=overflow, concise=fitting),
        'bare_array': fitting,
    }
    wire = json.dumps({'addition_1_text': variants[authoring]})
    revised, original, calls = copy_request([response(wire)])
    expected = original.model_copy(deep=True)
    expected.additions[1].text = ' '.join(fitting)
    assert revised == expected
    assert calls == 1


@pytest.mark.parametrize('shape', ['both_over', 'bare_over', 'malformed', 'duplicate', 'unrequested',
                                   'foreign_version', 'truncated'])
def test_incomplete_ambiguous_or_over_capacity_replies_cannot_supply_a_patch(shape):
    asymmetric = json.dumps(boundary_clauses())
    wire = '{"addition_1_text":' + asymmetric + '}'
    overflow = boundary_clauses(158)
    if shape == 'both_over':
        wire = json.dumps({'addition_1_text': dict(complete=overflow, concise=overflow)})
    elif shape == 'bare_over':
        wire = json.dumps({'addition_1_text': overflow})
    elif shape == 'malformed':
        wire = wire[:-1] + ',}'
    elif shape == 'duplicate':
        wire = '{"addition_1_text":["Conflicting version."],"addition_1_text":' + asymmetric + '}'
    elif shape == 'unrequested':
        wire = json.dumps({'addition_1_text': boundary_clauses(), 'addition_0_text': 'Foreign edit.'})
    elif shape == 'foreign_version':
        wire = json.dumps({'addition_1_text': dict(complete=boundary_clauses(), concise=['Short.'],
                                                  third=['Foreign variant.'])})
    outputs = [response(wire)]
    if shape == 'both_over':
        # Both author-supplied versions exceed the measured limit. A targeted
        # follow-up with no replacement clauses still cannot produce a patch.
        outputs.append(response('{}'))
    if shape == 'truncated':
        outputs = [response(wire[:-1], finish='length') for _ in range(2)]
    with pytest.raises((ValueError, LLMStructuredOutputError)):
        copy_request(outputs)
