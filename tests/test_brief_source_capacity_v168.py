"""Initial selection leaves space for independently reviewed material sources."""
import pytest

from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.models.coverage import SourceCheck, SourceCoverage
from tests.test_executive_brief import gateway, result_for
from tests.test_brief_item_repair import item, audited


def case():
    texts = [f'Measure {i} was reported.' for i in range(7)]
    result = result_for([' '.join(texts)])
    result.profile.source_coverage = SourceCoverage(checks=[SourceCheck(
        section_id=f'source-{i}', pages=[1], reason='Read conditions',
        decision_impact='Potential qualification', status='checked_not_found') for i in range(2)])
    draft = dict(title='Findings', items=[item(t) for t in texts])
    return result, draft


def test_overfull_initial_draft_uses_model_selection_before_locking():
    result, draft = case()
    indices = [0, 1, 3, 4, 6]
    g, client = gateway([draft, dict(indices=indices)])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert [i.text for i in brief.items] == [draft['items'][i]['text'] for i in indices]
    assert audited(result)['selection']['indices'] == indices
    assert audited(result)['discarded_candidate_indices'] == [2, 5]
    assert '"maximum_findings": 5' in client.editorial_calls[0][1]['content']
    assert len(client.editorial_calls) == 2


def test_model_cannot_consume_reserved_slots_in_its_selection():
    result, draft = case()
    g, _ = gateway([draft, dict(indices=list(range(7)))])
    with pytest.raises(ValueError, match='invalid or duplicate'):
        ExecutiveBriefWriter(g).generate(result)
