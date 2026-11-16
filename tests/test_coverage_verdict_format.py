"""Missing rationale recovery preserves rejection, evidence issues and retry bounds."""
import json
import pytest

from adaptive_document_agent.agent.coverage_verdict_format import complete_coverage_verdict
from adaptive_document_agent.agent.retained_selection_coverage import RetainedSelectionCoverage
from adaptive_document_agent.services.llm.exceptions import LLMResponseError,LLMStructuredOutputError
from tests.test_retained_analysis_v216 import gateway,_linked_result


def original():
    return dict(accepted=False,missing_insight_ids=[],prioritized_insight_ids=[],
                page_issues=[dict(insight_id='sample-page',reason='Preserve the original source condition.')])


def run(responses):
    client=gateway(responses);result=_linked_result();audit={}
    messages=[dict(role='system',content='Review the complete source.'),
              dict(role='user',content='Synthetic original source and complete page context.')]
    value=complete_coverage_verdict(client,messages,RetainedSelectionCoverage,audit,result,
                                   token_limits=(12000,20000))
    return value,client,result,audit


def test_missing_reason_is_completed_without_erasing_a_rejection():
    rejected=original();repaired={**rejected,'reason':'The page lacks a required source qualification.'}
    value,client,result,audit=run([rejected,repaired])
    assert not value.accepted and value.page_issues[0].reason==rejected['page_issues'][0]['reason']
    assert len(client.client.calls)==2
    assert any('Synthetic original source and complete page context.' in m['content']
               for m in client.client.calls[-1])
    record=json.loads(next(w.message for w in result.validation_warnings
                           if w.code=='retained_coverage_format_repair'))
    assert record['status']=='repaired' and not record['semantic_approval']
    assert json.loads(record['raw_response'])==rejected
    assert audit['output_attempts'][0]['status']=='invalid_format'


@pytest.mark.parametrize('mutation',[
    dict(accepted=True,page_issues=[]),dict(page_issues=[]),
    dict(page_issues=[dict(insight_id='other-page',reason='Preserve the original source condition.')]),
    dict(page_issues=[dict(insight_id='sample-page',reason='Changed source judgment.')]),
    dict(missing_insight_ids=['other-finding'],prioritized_insight_ids=['other-finding']),
])
def test_rationale_recovery_cannot_change_other_verdict_fields(mutation):
    with pytest.raises(LLMResponseError,match='changed the substantive verdict'):
        run([original(),{**original(),'reason':'Complete reason.',**mutation}])


def test_rationale_recovery_is_one_attempt_and_invalid_second_output_is_terminal():
    client=gateway([original(),original(),{**original(),'reason':'Forbidden third reply.'}])
    result=_linked_result()
    with pytest.raises(LLMStructuredOutputError):
        complete_coverage_verdict(client,[],RetainedSelectionCoverage,{},result,token_limits=(12000,20000))
    assert len(client.client.calls)==2
    record=json.loads(result.validation_warnings[-1].message)
    assert record['status']=='failed' and not record['semantic_approval']


def test_other_missing_substantive_fields_cannot_use_reason_only_correction():
    rejected=original();rejected.pop('accepted')
    client=gateway([rejected])
    with pytest.raises(LLMStructuredOutputError):
        complete_coverage_verdict(client,[],RetainedSelectionCoverage,{},_linked_result(),
                                  token_limits=(12000,20000))
    assert len(client.client.calls)==1
