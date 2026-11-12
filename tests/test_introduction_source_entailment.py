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
