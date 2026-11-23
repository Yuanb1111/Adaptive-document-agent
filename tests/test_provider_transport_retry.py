"""Unclassified transport errors have one retry without weakening known client errors."""
from types import ModuleType
import sys

import pytest

from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider,_attempts
from adaptive_document_agent.services.llm import LLMSettings,ProviderName
from tests.test_litellm_provider import _provider,UnsupportedParamsError
from pydantic import SecretStr


class APIError(Exception):
    def __init__(self,status=None):self.status_code=status


@pytest.mark.parametrize('status,expected',[
    (None,True),(-1,True),(500,True),(529,True),('503',True),(409,True),
    (400,False),(401,False),(402,False),(403,False),(404,False),(422,False),(501,False),
])
def test_only_unknown_transport_or_eligible_http_errors_retry(status,expected):
    assert LiteLLMProvider._transient_failure(APIError(status))==expected


@pytest.mark.parametrize('repeats',[False,True])
def test_compatibility_then_transport_failure_has_only_one_network_retry(monkeypatch,repeats):
    calls=[];module=ModuleType('litellm')
    def complete(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise UnsupportedParamsError('unsupported temperature')
        if len(calls)==2 or repeats:raise APIError()
        return object()
    module.completion=complete
    monkeypatch.setitem(sys.modules,'litellm',module)
    monkeypatch.setattr('adaptive_document_agent.services.llm.litellm_provider.time.sleep',lambda _:None)
    log=[];token=_attempts.set(log)
    try:
        if repeats:
            with pytest.raises(APIError):_provider()._completion([],temperature=0,max_tokens=123)
        else:_provider()._completion([],temperature=0,max_tokens=123)
    finally:_attempts.reset(token)
    assert len(calls)==3
    assert all('temperature' not in c and c['max_tokens']==123 for c in calls[1:])
    assert [a['kind'] for a in log]==['initial','compatibility_retry','network_retry']
    assert all('api_key' not in a and 'message' not in a for a in log)


def test_no_http_authentication_error_does_not_get_generic_api_error_retry():
    class AuthenticationError(Exception):pass
    assert not LiteLLMProvider._transient_failure(AuthenticationError())


@pytest.mark.parametrize('model',['gpt-6-luna','openai/gpt-6-luna'])
def test_official_luna_omits_rejected_temperature_before_first_request(monkeypatch,model):
    calls=[];module=ModuleType('litellm')
    def complete(**kwargs):
        calls.append(kwargs)
        if 'temperature' in kwargs:
            raise UnsupportedParamsError('gpt-6-luna does not support temperature')
        return object()
    module.completion=complete
    monkeypatch.setitem(sys.modules,'litellm',module)
    client=LiteLLMProvider(LLMSettings(provider=ProviderName.OPENAI,model=model,
        api_key=SecretStr('dummy-test-key')))
    log=[];token=_attempts.set(log)
    try:
        client._completion([],temperature=0,max_tokens=123)
    finally:
        _attempts.reset(token)
    assert len(calls)==1 and 'temperature' not in calls[0]
    assert calls[0]['model']==model if model.startswith('openai/') else calls[0]['model']=='openai/'+model
    assert [attempt['kind'] for attempt in log]==['initial']
    assert not log[0].get('compatibility_downgrade')
