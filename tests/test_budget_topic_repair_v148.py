"""Budget copy repair precedes native measurement and fresh omission review."""

from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent import executive_brief, topic_takeaway_repair, topic_plan_compiler
from adaptive_document_agent.models import DocumentPage
from tests.test_physical_budget_refinement_v130 import measurement, source
from tests.test_budget_output_v145 import failure_audit


def _payload(messages):
    return json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


@pytest.mark.parametrize('accepted', [True, False])
def test_repaired_budget_copy_is_measured_and_independently_reviewed_before_commit(monkeypatch, accepted):
    result, _, original, draft = source()
    result.presentation_plan.company.name = 'Source-owned identity'
    result.presentation_plan.company.source_pages = [1]
    result.presentation_plan.company.field_source_pages = {'name': [1]}
    result.document.pages = [DocumentPage(page_number=1, text='Source-owned identity')]
    raw = deepcopy(result.observations)
    events, notifications, measured_topics, reviewed_topics = [], [], [], []
    initial = original.model_dump()
    memos = []
    corrected = 'Output declined from 90 units in 6M2023 to 70 units in 6M2024.'

    def repair(gateway, current, plan, *, rejected_memo=None):
        memos.append(rejected_memo)
        events.append('repair')
        assert result.presentation_topics.model_dump() == initial
        assert current.presentation_topics.topics[0].series_ids == draft.topics[0].series_ids
        current.presentation_topics.topics[0].title = 'Output across the retained interim periods'
        current.presentation_topics.topics[0].takeaway = corrected
        return topic_plan_compiler.compile_topic_plan(current)

    def measure(current):
        is_original = len(current.presentation_topics.topics) == 3
        events.append('measure_original' if is_original else 'measure_repaired')
        if not is_original:
            assert current.presentation_plan.company.name == 'Source-owned identity'
            assert current.presentation_topics.topics[0].takeaway == corrected
            measured_topics.append(current.presentation_topics.model_dump(mode='json'))
        return measurement(current, 23 if is_original else 18, 12 if is_original else 8)

    def brief(self, current):
        events.append('brief')
        assert reviewed_topics[-1] == [topic.model_dump(mode='json') for topic in current.presentation_topics.topics]
        return None

    monkeypatch.setattr(topic_takeaway_repair, 'repair_withheld_takeaways', repair)
    monkeypatch.setattr(budget, 'measure', measure)
    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', brief)

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            if schema is budget.PhysicalBudgetSelection:
                events.append('selection')
                return draft.model_copy(deep=True)
            assert schema is budget.PhysicalBudgetReview
            events.append('review')
            proposal = _payload(messages)['proposal']
            reviewed_topics.append(proposal['topics'])
            assert proposal['topics'][0]['takeaway'] == corrected
            assert proposal['decisions'] == [decision.model_dump() for decision in draft.decisions]
            assert [topic['series_ids'] for topic in proposal['topics']] == [topic.series_ids for topic in draft.topics]
            assert result.presentation_topics.model_dump() == initial
            return schema(accepted=accepted, reason='Independent source and omission decision.')

    if accepted:
        assert budget.refine_presentation_budget(Gateway(), result, progress=notifications.append)
        assert events == ['measure_original', 'selection', 'repair', 'measure_repaired',
                          'review', 'brief', 'measure_repaired']
        audit = json.loads(next(w.message for w in result.validation_warnings
                               if w.code == 'presentation_physical_budget_review'))
        final = audit['attempts'][0]
        assert final['proposal']['topics'][0]['takeaway'] != corrected
        assert final['review_target']['topics'] == reviewed_topics[0]
        assert final['applied_selection']['topics'] == reviewed_topics[0]
        assert final['applied_selection'] == result.presentation_topics.model_dump(mode='json')
        assert final['timings_ms'].keys() == {'selection', 'compilation_and_source_checks',
            'native_measurement', 'independent_review', 'final_briefing', 'final_native_measurement'}
        assert all(type(value) is int and value >= 0 for value in final['timings_ms'].values())
        assert notifications == [
            'Refining analytical priorities using actual physical slide costs',
            'Budget proposal 1/2: choosing evidence priorities',
            'Budget proposal 1/2: compiling and checking selected findings',
            'Budget proposal 1/2: measuring native PowerPoint pages',
            'Budget proposal 1/2: independently reviewing scope and omissions',
            'Regenerating and independently checking the briefing against the final budgeted topics',
            'Measuring the final briefing and complete PowerPoint budget']
    else:
        with pytest.raises(ValueError, match='independently rejected'):
            budget.refine_presentation_budget(Gateway(), result, progress=notifications.append)
        assert result.presentation_topics == original
        assert events.count('review') == 2 and 'brief' not in events
        assert all(not attempt['independent_review']['accepted']
                   for attempt in failure_audit(result)['attempts'])
        assert memos[0] is not None and memos[0] is memos[1]
    assert result.observations == raw


def test_raw_source_mutation_during_takeaway_repair_never_reaches_review(monkeypatch):
    result, _, original, draft = source()
    before = deepcopy(result.observations)
    monkeypatch.setattr(budget, 'measure', lambda current: measurement(current, 23, 12))
    reviews = []

    def corrupt(gateway, current, plan, *, rejected_memo=None):
        current.observations[0].raw_value = 'untrusted source mutation'
        return plan

    monkeypatch.setattr(topic_takeaway_repair, 'repair_withheld_takeaways', corrupt)

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            if schema is budget.PhysicalBudgetSelection:
                return draft.model_copy(deep=True)
            reviews.append(schema.__name__)
            raise AssertionError('A source mutation cannot reach omission review')

    with pytest.raises(ValueError, match='changed retained extraction'):
        budget.refine_presentation_budget(Gateway(), result)
    assert not reviews
    assert result.observations == before and result.presentation_topics == original


def test_takeaway_repair_cannot_restore_an_omitted_source_series_before_review(monkeypatch):
    result, _, original, draft = source()
    monkeypatch.setattr(budget, 'measure', lambda current: measurement(current,
        23 if len(current.presentation_topics.topics) == 3 else 18,
        12 if len(current.presentation_topics.topics) == 3 else 8))
    omitted = next(decision.series_id for decision in draft.decisions if not decision.include)
    reviews = []

    def change_scope(gateway, current, plan, *, rejected_memo=None):
        current.presentation_topics.topics[0].series_ids = [omitted]
        return plan

    monkeypatch.setattr(topic_takeaway_repair, 'repair_withheld_takeaways', change_scope)

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            if schema is budget.PhysicalBudgetSelection:
                return draft.model_copy(deep=True)
            reviews.append(schema.__name__)
            raise AssertionError('A copy repair cannot approve a different source selection')

    with pytest.raises(ValueError, match='every original series'):
        budget.refine_presentation_budget(Gateway(), result)
    assert not reviews and result.presentation_topics == original
