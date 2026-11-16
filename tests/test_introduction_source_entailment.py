"""An accepted audience inventory cannot make an unsupported stronger fact mandatory."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from tests.test_compact_summary_v111 import fixture
from tests.introduction_review_helpers import review_payload,review_response


def test_fast_inventory_repairs_a_strengthened_assertion_before_audience_authoring():
    result,reading,_=fixture(1)
    source='The platform is among the top three providers for scheduling.'
    reading.parts[0].source_text=source
    before=deepcopy(reading.parts)
    calls=[]
    class Gateway:
        discovery_workers=8
        def generate_structured(self,messages,schema,**kwargs):
            calls.append(schema.__name__)
            if schema.__name__=='IntroductionAudienceSelection':
                return schema(decisions=[dict(part_id='part-0',include=True,reason='Service position.',
                    required_meanings=[dict(meaning='The platform ranks third for scheduling.')])])
            if schema.__name__=='IntroductionMeaningRevision':
                return schema(edits=[dict(meaning_id='meaning-0',required_meanings=[dict(meaning=source)])])
            payload=review_payload(messages)
            focused='source entailment ONLY' in messages[0]['content']
            strengthened=payload['current_meanings'][0]['meaning']!=source
            return review_response(schema,messages,accepted=not (focused and strengthened),repair_scope='meanings',
                reason='Membership does not establish the exact ordinal rank.' if focused and strengthened
                       else 'The original source supports this current assertion.')
    select_introduction_audience(Gateway(),result,reading)
    assert calls==['IntroductionAudienceSelection','IntroductionAudienceReview','IntroductionAudienceReview',
                   'IntroductionMeaningRevision','IntroductionAudienceReview','IntroductionAudienceReview']
    assert reading.parts==before and reading.audience_part_ids==['part-0']
    assert reading.audience_selection['decisions'][0]['required_meanings'][0]['meaning']==source
    assert reading.audience_selection['attempts'][0]['selection_review']['accepted']
    assert not reading.audience_selection['attempts'][0]['source_entailment_review']['accepted']
    assert reading.audience_selection['independent_review']['accepted']


def test_failed_source_entailment_request_cannot_inherit_broad_selection_acceptance():
    result,reading,_=fixture(1)
    class Gateway:
        discovery_workers=8
        calls=0
        def generate_structured(self,messages,schema,**kwargs):
            if schema.__name__=='IntroductionAudienceSelection':
                return schema(decisions=[dict(part_id='part-0',include=True,reason='Scope.',
                    required_meanings=[dict(meaning='Team AA supports scheduling.')])])
            self.calls+=1
            if self.calls==2:raise ValueError('Source entailment could not be checked')
            return review_response(schema,messages,accepted=True,reason='Selection is relevant.')
    with pytest.raises(ValueError,match='Source entailment could not be checked'):
        select_introduction_audience(Gateway(),result,reading)
    assert reading.audience_part_ids is None and not reading.audience_selection


@pytest.mark.parametrize('claims',[
    ('The service ranked among the top four providers by appointment count in 2025.',
     'The service had the largest regional share by appointment count in 2025.',
     'The service had the largest regional share in 2025.'),
    ('The survey found greater flexibility among participating remote staff.',
     'The survey found stronger satisfaction among participating remote staff.',
     'The survey found stronger satisfaction.'),
    ('The platform supports scheduling only after staff training.',
     'The platform supports coordination only after staff training.',
     'The platform supports coordination.'),
])
@pytest.mark.parametrize('correct',[True,False])
def test_split_assertions_each_require_their_own_shared_source_qualification(claims,correct):
    first,qualified,unqualified=claims
    result,reading,_=fixture(1)
    reading.parts[0].source_text=first+' '+qualified
    original=deepcopy(reading.parts)
    class Gateway:
        discovery_workers=8
        def generate_structured(self,messages,schema,**kwargs):
            if schema.__name__=='IntroductionAudienceSelection':
                return schema(decisions=[dict(part_id='part-0',include=True,reason='Core source context.',
                    required_meanings=[dict(meaning=first),dict(meaning=unqualified)])])
            if schema.__name__=='IntroductionMeaningRevision':
                return schema(edits=[dict(meaning_id='meaning-0',required_meanings=[dict(meaning=first)]),
                    dict(meaning_id='meaning-1',required_meanings=[dict(
                        meaning=qualified if correct else unqualified)])])
            payload=review_payload(messages)
            focused='source entailment ONLY' in messages[0]['content']
            target=payload['current_meanings'][1]
            rejected=focused and target['meaning']!=qualified
            return review_response(schema,messages,accepted=not rejected,repair_scope='meanings',
                reason='A sibling cannot supply this assertion’s necessary scope.' if rejected
                       else 'Current assertions preserve their complete source qualifications.',
                findings=[dict(kind='meaning',issue_type='missing_qualification',
                    part_id=target['part_id'],meaning_id=target['meaning_id'],
                    current_meaning=target['meaning'],source_quote=reading.parts[0].source_text,
                    reason='Repeat the shared source qualification in this assertion.')] if rejected else [])
    if correct:
        select_introduction_audience(Gateway(),result,reading)
        assert [m['meaning'] for m in reading.audience_selection['decisions'][0]['required_meanings']]==[first,qualified]
        assert reading.audience_selection['independent_review']['accepted']
    else:
        with pytest.raises(ValueError):select_introduction_audience(Gateway(),result,reading)
        assert reading.audience_part_ids is None and not reading.audience_selection
    assert reading.parts==original


@pytest.mark.parametrize('correct',[True,False])
def test_unclear_basis_is_disclosed_without_lending_a_neighboring_measure_to_a_rank(correct):
    result,reading,_=fixture(1)
    reading.parts[0].source_text=('According to the study, the service is among the top three providers, '
        'with a regional share of twelve percent measured by appointment count.')
    original=deepcopy(reading.parts)
    unsupported='According to the study, the service is among the top three providers by appointment count.'
    conservative=('According to the study, the service is among the top three providers; '
                  'a separate measurement basis for the ranking is not explicit in this passage.')
    share='The study reports a regional share of twelve percent measured by appointment count.'
    class Gateway:
        discovery_workers=8
        def generate_structured(self,messages,schema,**kwargs):
            if schema.__name__=='IntroductionAudienceSelection':
                return schema(decisions=[dict(part_id='part-0',include=True,reason='Service position and scope.',
                    required_meanings=[dict(meaning=unsupported),dict(meaning=share)])])
            if schema.__name__=='IntroductionMeaningRevision':
                return schema(edits=[dict(meaning_id='meaning-0',required_meanings=[dict(
                    meaning=conservative if correct else unsupported)]),
                    dict(meaning_id='meaning-1',required_meanings=[dict(meaning=share)])])
            payload=review_payload(messages)
            row=payload['current_meanings'][0]
            rejected='source entailment ONLY' in messages[0]['content'] and row['meaning']!=conservative
            return review_response(schema,messages,accepted=not rejected,repair_scope='meanings',
                reason='The adjacent share cannot establish the ranking basis.' if rejected
                       else 'The current source-attributed claims preserve disclosed scope and uncertainty.',
                findings=[dict(kind='meaning',issue_type='unsupported_assertion',part_id=row['part_id'],
                    meaning_id=row['meaning_id'],current_meaning=row['meaning'],
                    source_quote=reading.parts[0].source_text,reason='Remove the unestablished basis and disclose the limitation.')]
                    if rejected else [])
    if correct:
        select_introduction_audience(Gateway(),result,reading)
        assert [m['meaning'] for m in reading.audience_selection['decisions'][0]['required_meanings']]==[conservative,share]
        assert reading.audience_selection['independent_review']['accepted']
    else:
        with pytest.raises(ValueError):select_introduction_audience(Gateway(),result,reading)
        assert reading.audience_part_ids is None and not reading.audience_selection
    assert reading.parts==original
