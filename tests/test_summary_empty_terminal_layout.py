"""An invented empty EOF record cannot own, hide or change a real source line."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.summary_reader import SummaryReadBatch
from adaptive_document_agent.agent.summary_span_ownership import quarantine_empty_terminal_layout


def sample():
    block=SimpleNamespace(id='b',text='First literal source line.\nSecond literal source line.\nThird literal source line.')
    content=dict(block_id='b',start_line=1,end_line=3,title='Terms',role='content',
        reading_note='The supplied terms.',facts=[dict(label='Terms',text='First literal source line.',
            quote_start_line=1,quote_end_line=1)])
    tail=dict(block_id='b',start_line=4,end_line=4,title='Blank layout',role='layout',
              reading_note='Blank layout after the source.',facts=[])
    return block,SummaryReadBatch(parts=[content,tail])


def test_quarantine_retains_exact_original_facts_and_all_real_ownership():
    block,response=sample();before=deepcopy(response);record={}
    fixed=quarantine_empty_terminal_layout(response,[block],record)
    assert fixed.parts==response.parts[:1] and response==before
    assert record['quarantined_empty_terminal_layout']==[response.parts[1].model_dump(mode='json')]


@pytest.mark.parametrize('defect',['content','heading','facts','far_endpoint','crossing','gap','overlap','unknown'])
def test_real_missing_overlapping_or_substantive_source_is_never_repaired_by_quarantine(defect):
    block,response=sample();tail=response.parts[-1]
    if defect in {'content','heading'}:tail.role=defect
    elif defect=='facts':tail.facts=deepcopy(response.parts[0].facts)
    elif defect=='far_endpoint':tail.start_line=tail.end_line=5
    elif defect=='crossing':tail.start_line=3
    elif defect=='gap':response.parts[0].end_line=2
    elif defect=='overlap':response.parts.insert(1,response.parts[0].model_copy(deep=True))
    else:tail.block_id='unknown'
    before=deepcopy(response);record={}
    assert quarantine_empty_terminal_layout(response,[block],record)==before and not record
