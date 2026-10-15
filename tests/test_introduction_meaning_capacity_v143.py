"""One full regeneration handles output exhaustion; semantic approval stays separate."""

from concurrent.futures import CancelledError
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.introduction_audience import IntroductionAudienceSelection
from adaptive_document_agent.agent.introduction_meaning_repair import (
    IntroductionMeaningRevision, MEANING_REVISION_TOKEN_LIMITS, repair_meanings,
)
from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import (
    LLMResponseError, LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from adaptive_document_agent.services.llm.usage import LLMUsage
from tests.test_compact_summary_v111 import fixture
from tests.test_introduction_meaning_inventory_v139 import context


def repair_context():
    _,reading,_=fixture(3)
    source=dict(purpose="Explain the scheduling service and its prerequisites.",
        parts=[part.model_dump(exclude={"facts"}) for part in reading.parts])
    selection=IntroductionAudienceSelection(decisions=[dict(part_id=part.id,include=index<2,
        reason="The delivery prerequisite defines the service." if index<2 else "Redundant team example.",
        required_meanings=[dict(meaning=("Team AA supports scheduling and requires staff training before service delivery."
            if index==0 else "Team AB requires staff training before service delivery."))] if index<2 else [])
        for index,part in enumerate(reading.parts)])
    return reading,source,selection


def truncated(*, finish="length", text='{"edits":[{"meaning_id":"partial-untrusted"', usage=True):
    return LLMStructuredOutputError("Synthetic output failure with private diagnostic sentinel",response=LLMResponse(
        text=text,usage=LLMUsage(provider="mock",model="offline-capacity-fixture",output_tokens=16000,
            reasoning_tokens=16000,finish_reason=finish) if usage else None,
        attempts=[dict(status="success")]))


def corrected(payload):
    return IntroductionMeaningRevision(edits=[dict(meaning_id=item["meaning_id"],required_meanings=[
        dict(meaning="Team AA supports scheduling."),
        dict(meaning="Team AA requires staff training before service delivery.")]
        if item["part_id"]=="part-0" else [dict(meaning=item["meaning"])])
        for item in payload["original_meanings"]])


class CapacityGateway:
    def __init__(self,reading,events):
        self.reading,self.events=reading,list(events)
        self.calls=[]

    def generate_structured(self,messages,schema,**kwargs):
        assert schema is IntroductionMeaningRevision
        assert kwargs["stage"]=="presentation" and kwargs["allow_repair"] is False
        assert "reasoning_effort" not in kwargs and "extra_body" not in kwargs
        assert self.reading.plan_audits[-1]["status"]=="pending"
        self.calls.append((deepcopy(messages),dict(kwargs)))
        event=self.events.pop(0)
        if isinstance(event,BaseException):raise event
        return event(context(messages)) if callable(event) else event


def attempts(reading):
    return [item for item in reading.plan_audits if "introduction_meaning_revision_attempt" in item]


def test_truncated_reasoning_regenerates_full_unchanged_source_once_with_audited_capacity():
    reading,source,selection=repair_context()
    original=(deepcopy(source),selection.model_dump(),deepcopy(reading.parts))
    gateway=CapacityGateway(reading,[truncated(),corrected])
    draft=repair_meanings(gateway,source,selection,"Split the bundled assertion.",reading)
    assert [call[1]["max_tokens"] for call in gateway.calls]==list(MEANING_REVISION_TOKEN_LIMITS)
    assert gateway.calls[0][0]==gateway.calls[1][0]
    payload=context(gateway.calls[1][0])
    assert payload["source"]==source and len(payload["source"]["parts"])==3
    assert [item["meaning_id"] for item in payload["original_meanings"]]==["meaning-0","meaning-1"]
    assert "partial-untrusted" not in json.dumps(payload)
    failed,success=attempts(reading)
    assert failed["status"]=="truncated" and failed["capacity_retry"] is True
    assert failed["usage"]["output_tokens"]==failed["usage"]["reasoning_tokens"]==16000
    assert failed["usage"]["finish_reason"]=="length"
    assert failed["transport_attempt_count"]==1
    assert failed["original_meaning_count"]==2
    assert success["status"]=="response_received"
    assert failed["meaning_inventory"]==success["meaning_inventory"]
    assert len(draft.decisions[0].required_meanings)==2
    assert draft.decisions[1:]==selection.decisions[1:]
    assert [(d.part_id,d.include,d.reason) for d in draft.decisions]==[(d.part_id,d.include,d.reason) for d in selection.decisions]
    assert reading.audience_part_ids is None and not reading.audience_selection
    assert reading.status=="incomplete"
    assert (source,selection.model_dump(),reading.parts)==original


def test_second_truncation_is_final_and_retains_both_failed_attempts_without_a_partial_mapping():
    reading,source,selection=repair_context()
    second=truncated(text='{"edits":[]')
    gateway=CapacityGateway(reading,[truncated(),second])
    with pytest.raises(LLMStructuredOutputError) as failure:
        repair_meanings(gateway,source,selection,"Split every assertion.",reading)
    assert failure.value is second and len(gateway.calls)==2
    assert [record["status"] for record in attempts(reading)]==["truncated","truncated"]
    assert [record["capacity_retry"] for record in attempts(reading)]==[True,False]
    assert not any("introduction_meaning_revision" in record for record in reading.plan_audits)
    assert reading.audience_part_ids is None and not reading.audience_selection


@pytest.mark.parametrize("failure",[
    truncated(finish="stop"),truncated(usage=False),
    LLMTransportError("private diagnostic sentinel"),PrivacyViolationError("private diagnostic sentinel"),
    LLMResponseError("private diagnostic sentinel"),ValueError("private diagnostic sentinel"),
    RuntimeError("private diagnostic sentinel"),CancelledError("private diagnostic sentinel"),
])
def test_only_proven_output_truncation_can_trigger_capacity_retry(failure):
    reading,source,selection=repair_context()
    gateway=CapacityGateway(reading,[failure,corrected])
    with pytest.raises(type(failure)) as raised:
        repair_meanings(gateway,source,selection,"Source-bound correction only.",reading)
    assert raised.value is failure and len(gateway.calls)==1
    record,=attempts(reading)
    assert record["status"]==("cancelled" if isinstance(failure,CancelledError) else "failed")
    assert record["capacity_retry"] is False and record["error_type"]==type(failure).__name__
    assert "private diagnostic sentinel" not in json.dumps(reading.plan_audits)
    assert reading.audience_part_ids is None and not reading.audience_selection


@pytest.mark.parametrize("fault",["missing","duplicate","unknown","reassigned_owner","empty","unchanged"])
def test_successful_capacity_retry_never_relaxes_exact_inventory_or_semantic_repair_bounds(fault):
    reading,source,selection=repair_context()
    original=selection.model_dump()
    def invalid(payload):
        response=corrected(payload).model_dump()
        if fault=="missing":response["edits"].pop()
        elif fault=="duplicate":response["edits"][1]["meaning_id"]="meaning-0"
        elif fault=="unknown":response["edits"][1]["meaning_id"]="unknown-original"
        elif fault=="reassigned_owner":response["edits"][0]["part_id"]="part-2"
        elif fault=="empty":response["edits"][0]["required_meanings"]=[]
        else:
            response["edits"]=[dict(meaning_id=item["meaning_id"],required_meanings=[dict(meaning=item["meaning"])])
                               for item in payload["original_meanings"]]
        return IntroductionMeaningRevision.model_validate(response)
    gateway=CapacityGateway(reading,[truncated(),invalid,corrected])
    with pytest.raises(ValueError):repair_meanings(gateway,source,selection,"Keep every owned assertion.",reading)
    assert len(gateway.calls)==2 and selection.model_dump()==original
    assert reading.audience_part_ids is None and not reading.audience_selection
    if fault in {"missing","duplicate","unknown","unchanged"}:
        assert reading.plan_audits[-1]["error"]
    else:
        assert attempts(reading)[-1]["status"]=="failed"


def test_actual_recorded_truncation_metadata_can_precede_explicit_synthetic_transport_only_success():
    """Optional private-artifact replay: no invented semantic approval or source fixture."""
    path=os.environ.get("ADA_INTRO_CAPACITY_REPLAY_JSON")
    if not path:pytest.skip("Set ADA_INTRO_CAPACITY_REPLAY_JSON for an explicit recorded-artifact replay")
    original_bytes=Path(path).read_bytes()
    result=json.loads(original_bytes)
    audit=next(json.loads(issue["message"]) for issue in result["validation_warnings"]
               if issue["code"]=="company_introduction_summary_audit")
    reading=SummaryReview.model_validate(audit)
    rejected=next(record for record in reading.plan_audits if "introduction_audience_attempt" in record)
    selection=IntroductionAudienceSelection(decisions=rejected["decisions"])
    usage=next(record for record in result["llm_usage"] if record["operation"]=="IntroductionMeaningRevision")
    assert usage["finish_reason"]=="length" and usage["response_chars"]==0
    recorded=LLMStructuredOutputError("Recorded output exhaustion; not a new provider request.",
        response=LLMResponse(text="",usage=LLMUsage.model_validate(usage)))
    source=dict(parts=[part.model_dump(exclude={"facts"}) for part in reading.parts if part.role=="content"])
    before=deepcopy(source),selection.model_dump(),deepcopy(reading.parts)
    def synthetic_transport(payload):
        edits=[dict(meaning_id=item["meaning_id"],required_meanings=[dict(meaning=item["meaning"])])
               for item in payload["original_meanings"]]
        # This diagnostic fixture is deliberately not claimed to be a real or
        # source-approved correction. It tests full mapping transport only.
        edits[0]["required_meanings"][0]["meaning"]+=" [Synthetic transport-only fixture.]"
        return IntroductionMeaningRevision(edits=edits)
    gateway=CapacityGateway(reading,[recorded,synthetic_transport])
    draft=repair_meanings(gateway,source,selection,rejected["review"]["reason"],reading)
    assert len(gateway.calls)==2 and gateway.calls[0][0]==gateway.calls[1][0]
    assert attempts(reading)[-2]["usage"]["output_tokens"]==usage["output_tokens"]
    assert sum(len(d.required_meanings) for d in draft.decisions)==sum(len(d.required_meanings) for d in selection.decisions)
    assert reading.audience_part_ids is None and not reading.audience_selection and reading.status=="incomplete"
    assert (source,selection.model_dump(),reading.parts)==before
    assert Path(path).read_bytes()==original_bytes
