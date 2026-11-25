from copy import deepcopy

import pytest

from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors, RejectedPageAttempt, RetainedPage
from adaptive_document_agent.agent.retained_qualitative_recovery import revise_rejected_descriptions
from tests.test_retained_analysis_v216 import gateway


def rejected_owner():
    quote = dict(page=7, text='During the reporting period, participants contributed over 16% of activity.')
    original = RetainedPage(title='Annual participant count', message='Annual participants numbered 289.',
        source_context=[dict(scope='the reporting period', description='reports participants contributed a minority of activity',
                             quote=quote)])
    last = original.model_copy(deep=True)
    last.message += ' The interim observation was 304, on a shorter reporting basis.'
    last.companion_ids = ['interim-count-row']
    last.source_context[0].description = 'reports participants contributed over 16% of activity'
    reasons = ['source_context must preserve qualitative meaning without unbound numbers.']
    attempt = RejectedPageAttempt(page=last, errors=reasons)
    failure = AuthoredPageErrors({'count': reasons}, rejected_attempts={'count': [attempt]})
    owner = dict(errors=['The source gives a lower bound only. Include the interim count with its own scope.'],
                 primary_observations=[], source_rows=[])
    return original, last, failure, dict(pages_to_correct={'count': owner}, source_pages=[quote])


def test_narrow_repair_keeps_bound_interim_count_and_literal_lower_bound():
    original, last, failure, packet = rejected_owner()
    response = 'reports that participants contributed to activity and gives a lower bound on their share'
    model = gateway([{'context-0': response}])
    checked = []

    def validate(pages):
        checked.append(deepcopy(pages['count']))
        return {}

    revised = revise_rejected_descriptions(model, 'count', failure, original=original,
        payload=packet, limit=1100, validate=validate)['count']
    expected = last.model_copy(deep=True)
    expected.source_context[0].description = response
    assert revised == expected == checked[-1]
    assert checked[0].message == last.message and checked[0].companion_ids == ['interim-count-row']
    assert [call['operation'] for call in model.usage] == ['RetainedDescriptionRevision']
    assert 'unstated opposite bound' in str(model.client.calls[0])
    assert '16%' in revised.source_context[0].quote.text and '16%' not in revised.source_context[0].description


@pytest.mark.parametrize('other_failure', [False, True])
def test_narrow_repair_rejects_unbound_metrics_or_other_failures_before_sending(other_failure):
    original, _, failure, packet = rejected_owner()
    if other_failure:
        failure.by_insight['count'].append('Existing numeric inputs are frozen.')
    model = gateway([])
    assert revise_rejected_descriptions(model, 'count', failure, original=original,
        payload=packet, limit=1100, validate=lambda pages: {'count': ['Unbound interim count']}) is None
    assert model.client.calls == []


def test_complete_qualitative_sentence_can_be_reused_after_two_numerical_rejections():
    import json

    original, last, failure, packet = rejected_owner()
    first = 'Reports that participants contributed to activity.'
    numerical = 'Participants contributed over 16% of activity.'
    qualification = 'The source gives a lower bound on the participants’ share of activity.'
    model = gateway([{'context-0': first + ' ' + numerical},
                     {'context-0': dict(concise=numerical, shorter=numerical)},
                     {'context-0': dict(sentence_ids=['sentence-1'], qualification=qualification)}])
    revised = revise_rejected_descriptions(model, 'count', failure, original=original, payload=packet,
        limit=1100, validate=lambda pages: {})['count']
    assert [call['operation'] for call in model.usage] == [
        'RetainedDescriptionRevision', 'RetainedDescriptionLengthRepair', 'RetainedQualitativeCopy']
    encoded = json.loads(model.client.calls[-1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert encoded['addressed_descriptions']['context-0']['eligible_sentences'] == {'sentence-1': first}
    assert encoded['frozen_headline'] == last.message
    expected = last.model_copy(deep=True)
    expected.source_context[0].description = first + ' ' + qualification
    assert revised == expected


def test_numeral_free_field_and_literal_sentence_ids_fail_closed():
    from pydantic import ValidationError
    from adaptive_document_agent.agent.retained_qualitative_copy import qualitative_copy
    _, last, _, _ = rejected_owner()
    original = 'Reports a minority contribution.'
    numerical = 'Reports participants contributed over 16%.'
    data = {'context-0': dict(local_validation_error='Unbound percentage',
        earlier_unapproved_wording=original, literal_proof=[last.source_context[0].quote.model_dump()])}

    class InvalidChoice:
        def generate_structured(self, messages, schema, **kwargs):
            with pytest.raises(ValidationError):
                schema.model_validate({'context-0': dict(sentence_ids=[], qualification=numerical)})
            return schema.model_validate({'context-0': dict(sentence_ids=['foreign-sentence'],
                qualification='The source gives a lower bound on their contribution.')})

    with pytest.raises(ValueError, match='distinct supplied sentence IDs'):
        qualitative_copy(InvalidChoice(), last, {'context-0': 0}, data,
            {'context-0': 'Reports a contribution to activity. ' + numerical},
            {'context-0': {'concise': numerical, 'shorter': numerical}}, [], [], 900)
