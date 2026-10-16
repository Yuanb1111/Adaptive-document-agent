"""Writable series addresses and actual native overhead remain distinct from evidence."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent.presentation_budget_contract import (
    editable_series_inventory, measured_budget_allocation, selection_inventory_diagnostics,
)
from adaptive_document_agent.models.customization import ReportRequirement, ReportRequirements
from adaptive_document_agent.models.presentation import PresentationOmission
from tests.test_physical_budget_refinement_v130 import measurement, source


def payload(messages, index=-1):
    return json.loads(messages[index]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


@pytest.mark.parametrize('field', ['omissions', 'selection', 'historical_omissions_read_only'])
def test_budget_wire_cannot_rewrite_or_duplicate_the_historical_omission_display_list(field):
    _, _, _, draft = source()
    value = draft.model_dump()
    value[field] = []
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        budget.PhysicalBudgetSelection.model_validate(value)
    assert set(budget.PhysicalBudgetSelection.model_json_schema()['properties']) == {'topics', 'decisions'}


def test_budget_topic_wire_rejects_an_unowned_field_instead_of_silently_ignoring_it():
    _, _, _, draft = source()
    value = draft.model_dump()
    value['topics'][0]['additional_evidence'] = ['unowned-series']
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        budget.PhysicalBudgetSelection.model_validate(value)


@pytest.mark.parametrize(('fault', 'field'), [
    ('missing', 'missing_series_ids'), ('unknown', 'extra_series_ids'),
    ('historical', 'extra_series_ids'), ('duplicate', 'duplicate_series_ids'),
    ('moved', 'moved_or_unknown_topic_series'), ('duplicate_topic', 'duplicate_topic_ids'),
    ('duplicate_topic_series', 'duplicate_topic_series'),
    ('include_mismatch', 'included_but_unselected_series_ids'),
])
def test_exact_inventory_diagnostics_fail_closed_without_moving_or_selecting_evidence(fault, field):
    result, lookup, original, draft = source()
    before = deepcopy(original)
    if fault == 'missing':
        draft.decisions.pop()
    elif fault == 'unknown':
        draft.decisions[0].series_id = 'never-owned-series'
    elif fault == 'historical':
        original.omissions = [PresentationOmission(series_id='historically-omitted', reason='Prior source-aware model decision.')]
        before = deepcopy(original)
        draft.decisions.append(budget.BudgetSeriesDecision(series_id='historically-omitted', include=False,
            reason='Copied historical entry is outside the editable ledger.'))
    elif fault == 'duplicate':
        draft.decisions.append(draft.decisions[0].model_copy())
    elif fault == 'moved':
        draft.topics[0].series_ids = original.topics[0].series_ids[:]
    elif fault == 'duplicate_topic':
        draft.topics.append(draft.topics[0].model_copy(deep=True))
    elif fault == 'duplicate_topic_series':
        draft.topics[0].series_ids *= 2
    else:
        draft.decisions[0].include = True
    diagnostics = selection_inventory_diagnostics(draft, original)
    assert diagnostics[field]
    with pytest.raises(ValueError, match=field):
        budget.validate_subset(draft, original, lookup, result)
    assert original == before


def cap(scope, maximum, *, section='report'):
    return ReportRequirement(id=scope+section, request_quote='Explicit physical budget.',
        description='Count actual native slides.', kind='slide_limit', max_slides=maximum,
        slide_scope=scope, slide_section=section)


@pytest.mark.parametrize(('caps', 'analysis_limit', 'expected'), [
    ([cap('body', 20)], 10, 7),
    ([cap('all', 20)], 10, 5),
    ([cap('body', 20), cap('all', 21)], 10, 6),
    ([cap('body', 20)], 4, 4),
    ([cap('body', 12)], 10, 0),
])
def test_current_physical_overhead_and_both_scope_caps_determine_writing_hint(caps, analysis_limit, expected):
    counts = dict(total=25, body=23, data_index=2, introduction=5, analysis=10)
    before = deepcopy(counts)
    allocation = measured_budget_allocation(counts, caps[0], ReportRequirements(items=caps),
        maximum_analysis_slides=analysis_limit)
    assert allocation['effective_analysis_capacity'] == expected
    assert allocation['current_non_intro_non_analysis_slides'] == (8 if caps[0].slide_scope == 'body' else 10)
    assert allocation['constraints'][0]['over_budget_by'] == max(0,
        counts['body' if caps[0].slide_scope == 'body' else 'total']-caps[0].max_slides)
    assert 'Final native export checks remain mandatory' in allocation['basis']
    assert counts == before


def test_one_extra_fallback_executive_page_consumes_actual_capacity_without_a_static_allowance():
    requirement = cap('body', 20)
    common = dict(total=24, body=22, data_index=2, introduction=5, analysis=10)
    two_page_brief = measured_budget_allocation(common, requirement, None, maximum_analysis_slides=10)
    three_page_brief = measured_budget_allocation({**common, 'total':25, 'body':23}, requirement, None,
        maximum_analysis_slides=10)
    assert two_page_brief['effective_analysis_capacity'] == 8
    assert three_page_brief['effective_analysis_capacity'] == 7


def test_complete_old_and_new_model_reasons_are_retained_without_expanding_the_display_field(monkeypatch):
    result, _, original, draft = source()
    from tests.test_topic_coverage_review import _observation
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    for index in range(12):
        result.observations += [_observation(f'Prior detail {index}', 'FY2022', index+1),
                                _observation(f'Prior detail {index}', 'FY2023', index+2)]
    directory, _ = series_directory(result)
    historical = [PresentationOmission(series_id=item['id'], reason=f'Original independent priority reason {index}.')
                  for index, item in enumerate(item for item in directory if item['metric'].startswith('Prior detail'))]
    assert len(historical) == 12
    original.omissions = historical
    result.presentation_topics = original
    raw = deepcopy(result.observations)
    monkeypatch.setattr(budget, 'measure', lambda current: measurement(current,
        23 if len(current.presentation_topics.topics) == 3 else 18,
        12 if len(current.presentation_topics.topics) == 3 else 8))
    from adaptive_document_agent.agent import executive_brief
    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', lambda *args: None)
    invalid = draft.model_copy(deep=True)
    invalid.decisions.append(budget.BudgetSeriesDecision(series_id=historical[0].series_id, include=False,
        reason='Historical IDs must not be repeated in the editable decision inventory.'))
    calls, review_sources = [], []
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            if schema is budget.PhysicalBudgetSelection:
                source_context = payload(messages, -1 if len(calls) == 1 else 2)
                assert source_context['historical_omissions_read_only'] == [item.model_dump() for item in historical]
                assert source_context['editable_series_inventory'] == editable_series_inventory(original)
                assert len(source_context['editable_series_inventory']) == 3
                assert 'original_selection' not in source_context
                if len(calls) == 1:
                    return invalid
                rejected = payload(messages, -2)
                assert rejected['inventory_diagnostics']['extra_series_ids'] == [historical[0].series_id]
                return draft
            review_sources.append(payload(messages))
            assert len(review_sources[0]['proposal']['decisions']) == 3
            assert review_sources[0]['proposal']['decisions'][0]['include'] is False
            return schema(accepted=True, reason='Fresh complete source and omission review accepts the actual selected comparisons.')
    assert budget.refine_presentation_budget(Client(), result)
    assert calls == ['PhysicalBudgetSelection', 'PhysicalBudgetSelection', 'PhysicalBudgetReview']
    assert result.presentation_topics.omissions == historical
    assert len(result.presentation_topics.omissions) == 12
    assert result.observations == raw
    audit = json.loads(next(issue.message for issue in result.validation_warnings
                           if issue.code == 'presentation_physical_budget_review'))
    assert audit['original_selection']['omissions'] == [item.model_dump() for item in historical]
    assert audit['attempts'][-1]['proposal']['decisions'] == [item.model_dump() for item in draft.decisions]
    assert audit['attempts'][-1]['applied_selection']['omissions'] == [item.model_dump() for item in historical]
    assert audit['attempts'][-1]['independent_review']['accepted'] is True
    assert audit['attempts'][0]['status'] == 'rejected'
