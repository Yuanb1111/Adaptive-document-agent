import pytest

from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft
from adaptive_document_agent.agent.summary_body_allocation import SummaryBodyAllocation, reallocate_body
from tests.test_summary_content_repair_v122 import draft


def test_body_reallocation_cannot_rewrite_or_remove_existing_appendix():
    original = draft()
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            assert schema is SummaryBodyAllocation
            return schema(body=[original.pages[0]], additions=[dict(page_index=1,
                item=dict(label='Support', text='Additional supported body context.', fact_ids=['f0']))])
    revised = reallocate_body(Client(), original, [], SummarySynthesisDraft, {})
    assert revised.pages[1].items[0].model_dump() == original.pages[1].items[0].model_dump()
    assert len(revised.pages[1].items) == 2
    assert revised.model_dump(exclude={'pages'}) == original.model_dump(exclude={'pages'})
    assert len(original.pages[1].items) == 1


@pytest.mark.parametrize('target', [0, 10])
def test_body_allocation_additions_cannot_target_body_or_unknown_page(target):
    original = draft()
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            return schema(body=[original.pages[0]], additions=[dict(page_index=target,
                item=dict(label='Support', text='Supported context.', fact_ids=['f0']))])
    with pytest.raises(ValueError, match='existing appendix'):
        reallocate_body(Client(), original, [], SummarySynthesisDraft, {})
