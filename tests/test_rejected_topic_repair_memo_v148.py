"""Only exact invocation-owned author failures can avoid a repeated request."""
import json
from concurrent.futures import CancelledError

import pytest
from pydantic import BaseModel, SecretStr

from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
from adaptive_document_agent.agent.topic_repair_memo import RejectedTopicRepairMemo
from adaptive_document_agent.agent.topic_takeaway_repair import repair_withheld_takeaways
from adaptive_document_agent.agent.presentation_topic_scope_recovery import withheld_topic_ids
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.config import LLMSettings, ProviderName, PrivacyMode
from adaptive_document_agent.services.llm.exceptions import LLMTransportError, PrivacyViolationError
from adaptive_document_agent.services.llm.mock import MockLLMClient
from tests.test_topic_scope_recovery_regressions import _synthetic_result


def case():
    result = _synthetic_result('metric_alias')
    plan = compile_topic_plan(result)
    rejected = result.presentation_topics.topics[0].takeaway
    client = MockLLMClient([{'takeaway': rejected}] * 12)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK), cache_enabled=False)
    return result, plan, gateway, RejectedTopicRepairMemo()


def repair(result, plan, gateway, memo):
    # Each budget proposal supplies a freshly compiled candidate; final
    # editorial stamping must not mutate the seed for the next proposal.
    updated = repair_withheld_takeaways(gateway, result, plan.model_copy(deep=True), rejected_memo=memo)
    assert withheld_topic_ids(updated) == {'scope'}
    return updated


def test_two_budget_candidates_reuse_only_the_two_exact_failed_author_requests_with_cache_off():
    result, plan, gateway, memo = case()
    before = result.model_dump(include={'document', 'observations', 'presentation_topics'})
    repair(result, plan, gateway, memo)
    repair(result, plan, gateway, memo)
    assert not gateway.cache_enabled and len(gateway.client.calls) == 2
    audits = [json.loads(w.message) for w in result.validation_warnings
              if w.code == 'presentation_topic_takeaway_repair']
    assert [a['status'] for a in audits] == ['rejected'] * 4
    assert all(a['semantic_approval'] is False for a in audits[2:])
    assert all(a['reused_failed_author_request'] for a in audits[2:])
    assert result.model_dump(include={'document', 'observations', 'presentation_topics'}) == before
    # A different budget invocation owns a different memo, even with cache off.
    repair(result, plan, gateway, RejectedTopicRepairMemo())
    assert len(gateway.client.calls) == 4


@pytest.mark.parametrize('changed', ['value', 'missing_value', 'raw_value', 'unit', 'source',
                                   'constraints', 'period', 'policy', 'temperature', 'privacy',
                                   'route', 'credential'])
def test_changed_source_constraints_and_generation_identity_do_not_reuse_failures(changed):
    result, plan, gateway, memo = case()
    repair(result, plan, gateway, memo)
    if changed == 'value': result.observations[0].value += 1
    elif changed == 'missing_value': result.observations[0].value = None
    elif changed == 'raw_value': result.observations[0].raw_value = '(999)'
    elif changed == 'unit': result.observations[0].unit_scale = 1000
    elif changed == 'source': result.observations[0].evidence[0].text += ' qualified source'
    elif changed == 'constraints': result.profile.analysis_page_ranges = [(8, 9)]
    elif changed == 'period': result.observations[0].period = 'FY2022'
    elif changed == 'policy': gateway.client.request_policy = lambda **kwargs: {'new_policy': True}
    elif changed == 'temperature': gateway.settings.temperature = 0.2
    elif changed == 'privacy': gateway.settings.privacy_mode = PrivacyMode.LOCAL_ONLY
    elif changed == 'route': gateway.settings.stage_models['presentation'] = 'different-route'
    else: gateway.settings.api_key = SecretStr('different-test-credential')
    repair(result, plan, gateway, memo)
    assert len(gateway.client.calls) == 4
    assert 'different-test-credential' not in repr(memo.__dict__)


def test_schema_and_client_identity_changes_invalidate_the_request_key():
    _, _, gateway, memo = case()
    class First(BaseModel): value: str
    class Second(BaseModel): value: int
    key = memo.key(gateway, [{'role': 'user', 'content': 'owned evidence'}], First, 'source')
    assert key is not None
    assert key != memo.key(gateway, [{'role': 'user', 'content': 'owned evidence'}], Second, 'source')
    gateway.client = MockLLMClient()
    assert key != memo.key(gateway, [{'role': 'user', 'content': 'owned evidence'}], First, 'source')
    assert memo.key(object(), [], First, 'source') is None


def test_successful_author_copy_is_not_memoized_as_an_approval():
    result, plan, gateway, memo = case()
    copy = {'takeaway': 'Loss for the year amounted to USD 140 in FY2023 and USD 230 in FY2025.'}
    gateway.client.responses.clear()
    gateway.client.responses.extend([copy, copy])
    first = repair_withheld_takeaways(gateway, result.model_copy(deep=True), plan, rejected_memo=memo)
    second = repair_withheld_takeaways(gateway, result.model_copy(deep=True), plan, rejected_memo=memo)
    assert not withheld_topic_ids(first) and not withheld_topic_ids(second)
    assert len(gateway.client.calls) == 2 and not memo._rejections


@pytest.mark.parametrize('error', [LLMTransportError('offline transport failure'),
                                 PrivacyViolationError('privacy block'), CancelledError('cancelled')])
def test_transport_privacy_and_cancellation_propagate_without_recording_a_reusable_verdict(error):
    result, plan, gateway, memo = case()
    def fail(*args, **kwargs): raise error
    gateway.client.generate_structured = fail
    with pytest.raises(type(error)):
        repair(result, plan, gateway, memo)
    assert not memo._rejections


def test_missing_required_response_value_is_never_treated_as_a_source_verdict():
    result, plan, gateway, memo = case()
    gateway.client.responses.clear()
    gateway.client.responses.extend([{}] * 4)
    repair(result, plan, gateway, memo)
    repair(result, plan, gateway, memo)
    assert len(gateway.client.calls) == 4 and not memo._rejections
