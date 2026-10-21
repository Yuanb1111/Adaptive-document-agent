"""Only source-bound model decisions remove duplicated qualifications."""
from copy import deepcopy
import json
import pytest
from adaptive_document_agent.agent.topic_caveat_review import reconcile_caveats
from adaptive_document_agent.models import PresentationTopicSelection
from tests.test_topic_coverage_review import _topic
from tests.test_pptx_export import _result


@pytest.mark.parametrize('fault', ['', 'missing', 'wrong_owner'])
def test_duplicate_footnote_removed_but_extra_period_qualification_survives(fault):
    topic=_topic('series');topic.caveats=['Others include service fees.','These periods are unaudited.']
    selection=PresentationTopicSelection(topics=[topic]);result=_result();before=deepcopy(selection)
    note=dict(label='Others',text='Others primarily represent service fees.',page=2,table_id='source',marker='1')
    directory=[dict(id='series',source_qualifications=[note])]
    class Gateway:
        def generate_structured(self,messages,schema,**kwargs):
            data=json.loads(messages[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0])
            assert data[0]['displayed_source_notes']==[note]
            decisions=[dict(topic_id=topic.id,caveat_index=0,duplicate=True,source_note_index=0,
                            reason='The whole fee scope is already in the complete displayed note.'),
                       dict(topic_id=topic.id,caveat_index=1,duplicate=False,
                            reason='The source fee note does not establish assurance status.')]
            if fault=='missing':decisions=decisions[:1]
            if fault=='wrong_owner':decisions[0]['source_note_index']=2
            return schema(decisions=decisions)
    reconcile_caveats(selection,directory,result,Gateway())
    assert selection==before if fault else selection.topics[0].caveats==['These periods are unaudited.']
    assert directory[0]['source_qualifications']==[note]
    assert json.loads(result.validation_warnings[-1].message)['status']==('unchanged' if fault else 'reviewed')
