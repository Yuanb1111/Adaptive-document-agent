"""Geometric improvement must not bypass final over-budget recovery."""
import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft, expand_compact
from adaptive_document_agent.agent.summary_layout_repair import paginate_draft
from tests.test_summary_layout_choices_v191 import fixture, Client


@pytest.mark.parametrize('repetitions', [8, 20])
def test_improved_but_over_budget_draft_reaches_measured_selector(repetitions):
    review, catalog, revised = fixture()
    initial = revised.model_copy(deep=True)
    for index, item in enumerate(initial.pages[0].items):
        item.text = ' '.join([review.parts[index].source_text.strip()] * repetitions)
        item.meaning_refs[0].summary_quote = item.text
    client, audit = Client(revised), {}
    final, pages = paginate_draft(client, initial, catalog, review, [], audit,
        expand_compact, CompactSummaryDraft)
    attempts = audit['layout_attempts']
    progress = attempts[1]['compression_progress']
    assert progress['improved'] is True
    assert progress['current']['body_slides'] > review.max_intro_slides
    if repetitions == 8:
        assert progress['previous']['body_slides'] == progress['current']['body_slides']
        assert progress['current']['estimated_body_occupied_inches'] < progress['previous']['estimated_body_occupied_inches']
    else:
        assert progress['previous']['body_slides'] > progress['current']['body_slides']
    assert client.operations == ['SummaryLayoutPages', 'SummaryLayoutChoice']
    assert attempts[1]['layout_choice_evaluation']['feasible'] is True
    assert len(pages) == review.max_intro_slides == 2
    assert [r['status'] for r in attempts] == ['overflow', 'overflow', 'success']
    assert review.status == 'incomplete'


def test_improvement_that_meets_budget_needs_no_selector():
    review, catalog, initial = fixture()
    from adaptive_document_agent.agent.summary_layout_choices import inline_group
    fitting = initial.model_copy(deep=True)
    fitting.pages[0] = inline_group(fitting.pages[0])
    client, audit = Client(fitting), {}
    _, pages = paginate_draft(client, initial, catalog, review, [], audit,
        expand_compact, CompactSummaryDraft)
    assert len(pages) == 2
    assert client.operations == ['SummaryLayoutPages']
    assert len(audit['layout_attempts']) == 2
