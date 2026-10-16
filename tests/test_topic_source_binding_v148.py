"""Literal source categories and independent period ranges retain valid claims."""

import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.services.presentation_claim_evidence import _narrow
from adaptive_document_agent.validation.direction_scope import _value_in_period_ranges
from adaptive_document_agent.validation.scoped_narrative_values import scoped_value_errors
from tests.test_p0_composition import observation


def _composition_rows():
    records = []
    for category, values in [('Inventories', (31, 47)), ('Cash balances', (83, 61))]:
        for index, amount in enumerate(values):
            item = observation(f'{category}-{index}', 'Current assets', amount * 1000, unit='currency')
            item.raw_value, item.raw_unit, item.unit_scale = str(amount), 'USD thousands', 1000
            item.category_dimensions = {'category': category}
            item.evidence[0].row_label = category
            records.append(item)
    return records


def test_literal_composition_category_owns_its_source_unit_values():
    records = _composition_rows()
    slide = PresentationSlide(id='composition', slide_type='analysis', title=(
        'Inventories rose from 31 to 47. Cash balances fell from USD83 thousand to USD61 thousand.'))
    assert not scoped_value_errors(slide, records)
    slide.title = 'Inventories fell from 83 to 61.'
    assert len(scoped_value_errors(slide, records)) == 2


def test_category_metadata_cannot_alias_a_different_source_row():
    records = _composition_rows()
    for item in records:
        if item.category_dimensions['category'] == 'Inventories':
            item.evidence[0].row_label = 'Unresolved row'
    unselected = observation('catalog-inventory', 'Inventories', 999)
    slide = PresentationSlide(id='composition', slide_type='analysis', title='Inventories rose from 31 to 47.')
    assert len(scoped_value_errors(slide, records, [*records, unselected])) == 2


def test_coordinated_independent_value_ranges_do_not_form_a_cross_basis_chain():
    text = ('Revenue rose from USD100 thousand in FY2021 to USD140 thousand in FY2023 '
            'and from USD41 thousand in 6M2023 to USD49 thousand in 6M2024.')
    assert [periods for periods, _ in _value_in_period_ranges(text)] == [
        ['FY2021', 'FY2023'], ['6M2023', '6M2024']]


def test_one_value_chain_still_requires_every_written_period():
    text = 'Revenue rose from 100 in FY2021 to 120 in FY2022 and 140 in FY2023.'
    assert [periods for periods, _ in _value_in_period_ranges(text)] == [['FY2021', 'FY2022', 'FY2023']]
    assert not _value_in_period_ranges('Revenue rose from 100 in FY2021 to 120 in FY2022 and FY2023.')


@pytest.mark.parametrize('interim_values,valid', [((41, 49), True), ((49, 41), False)])
def test_one_predicate_checks_each_explicit_annual_and_interim_comparison(interim_values, valid):
    from tests.test_segmented_direction_claims import _series, _slide
    from adaptive_document_agent.validation.claim_validator import ClaimValidator
    records = _series('Revenue', [100, 120, 140], years=(2021, 2022, 2023))
    interim = _series('Revenue', list(interim_values), years=(2023, 2024))
    for item in interim:
        item.id = 'interim-' + item.id
        item.period = item.period.replace('FY', '6M')
        item.period_type, item.period_basis = 'interim_flow', '6M'
    records += interim
    text = ('Revenue rose from 100 in FY2021 to 140 in FY2023 '
            f'and from {interim_values[0]} in 6M2023 to {interim_values[1]} in 6M2024.')
    issues = ClaimValidator().validate_slide(_slide(text, records), records)
    assert bool(issues) is not valid


@pytest.mark.parametrize('question', [
    'How did annual support expenditure and its expense ratio change from FY2021 to FY2023?',
    'How did customer groups compare across the reported periods?',
])
def test_rejected_share_claim_keeps_the_model_authored_neutral_question(question):
    slide = PresentationSlide(id='ratio', slide_type='analysis',
        title='Support spending rose while its share fell',
        section_title='Support spending rose while its share fell', analytical_question=question)
    _narrow(slide, {})
    assert slide.title == question
    assert slide.analytical_question == question
    assert slide.section_title == question


def test_assertive_question_cannot_survive_by_being_called_a_question():
    slide = PresentationSlide(id='ratio', slide_type='analysis', title='Share rose',
        analytical_question='How did the share increase to the highest level?')
    _narrow(slide, {})
    assert slide.title != 'How did the share increase to the highest level?'
    assert slide.analytical_question != 'How did the share increase to the highest level?'


def test_independent_topic_corrections_overlap_but_audits_follow_selected_order():
    import json
    from contextvars import ContextVar
    from threading import Barrier
    from types import SimpleNamespace
    from adaptive_document_agent.agent.topic_selection_repair import retain_valid_topics
    from adaptive_document_agent.models import PresentationTopic, PresentationTopicSelection

    barrier = Barrier(2)
    marker = ContextVar('repair-test-context', default='missing')
    marker.set('request-scope')
    result = SimpleNamespace(validation_warnings=[])
    topics = [PresentationTopic(id=key, title='Rejected claim', question='Which values are reported?',
        rationale='Retain the original evidence.', takeaway='Rejected claim', series_ids=[key])
        for key in ['first', 'second']]
    lookup = {key: [observation(key, 'Reported measure', 10)] for key in ['first', 'second']}

    class Gateway:
        discovery_workers = 2
        def generate_structured(self, messages, response_model, **kwargs):
            assert marker.get() == 'request-scope'
            barrier.wait(timeout=5)
            raise ValueError('Scoped wording remains unsupported')

    def validate(selection, lookup, **kwargs):
        if any(t.title == 'Rejected claim' for t in selection.topics):
            raise ValueError('Rejected claim')

    retained = retain_valid_topics(PresentationTopicSelection(topics=topics), lookup, None,
                                   result, Gateway(), validate)
    assert not retained.topics
    failures = [warning.related_ids[0] for warning in result.validation_warnings
                if warning.code == 'presentation_topic_validation'
                and json.loads(warning.message)['phase'] == 'correction_failed']
    assert failures == ['first', 'second']


def test_revised_model_takeaway_is_revalidated_instead_of_inheriting_a_stale_withdrawal():
    from tests.test_topic_scope_recovery_regressions import _synthetic_result
    from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
    from adaptive_document_agent.agent.presentation_topic_scope_recovery import withheld_topic_ids
    result = _synthetic_result('metric_alias')
    result.presentation_plan = compile_topic_plan(result)
    assert withheld_topic_ids(result.presentation_plan) == {'scope'}
    result.presentation_topics.topics[0].takeaway = (
        'Loss for the year amounted to USD 140 in FY2023 and USD 230 in FY2025.')
    revised = compile_topic_plan(result)
    assert not withheld_topic_ids(revised)
    assert any(note.startswith('[previous_claim_scope_withheld] ') for note in revised.editorial_notes)
    result.presentation_topics.topics[0].takeaway = 'Loss for the year amounted to USD 999999 in FY2025.'
    with pytest.raises(ValueError):
        compile_topic_plan(result)
