from copy import deepcopy

from adaptive_document_agent.agent.source_integration_resume import editable_rejected_sections
from adaptive_document_agent.agent.source_integration_review import SourceIntegrationVerdict
from tests.test_source_completion_capacity_v173 import _outputs


def test_all_rejected_full_capacity_additions_keep_owned_edit_scopes():
    draft, _ = _outputs('The contract may be cancelled without compensation.')
    draft.decisions[0].brief_item_indexes = [5]
    draft.additions.append(draft.additions[0].model_copy(deep=True))
    draft.decisions.append(draft.decisions[0].model_copy(update={
        'section_id': 'other', 'brief_item_indexes': [6]}))
    verdicts = {d.section_id: SourceIntegrationVerdict(section_id=d.section_id,
        accepted=False, reason='Correct this source qualification.') for d in draft.decisions}
    original = deepcopy(draft)
    assert editable_rejected_sections(draft, verdicts, 5, allow_full_capacity=True) == ['contracts', 'other']
    assert editable_rejected_sections(draft, verdicts, 5) == []
    assert draft == original
    # Free capacity can require different allocations or a new finding.
    assert editable_rejected_sections(draft, verdicts, 4) == []
    draft.decisions[1].disposition = 'omit'
    draft.decisions[1].brief_item_indexes = []
    assert editable_rejected_sections(draft, verdicts, 5) == []
