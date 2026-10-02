"""Whole-gateway admission bounds concurrent stages without global session state."""

from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest
from pydantic import BaseModel

from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMTransportError


class Answer(BaseModel):
    value: int = 1


class CountingClient(MockLLMClient):
    supports_concurrent_requests = True

    def __init__(self, limit, *, repair=False):
        super().__init__()
        self.lock = Lock()
        self.active = 0
        self.maximum = 0
        self.calls_started = 0
        self.limit = limit
        self.admitted = Event()
        self.release = Event()
        self.repair = repair

    def call(self):
        with self.lock:
            self.active += 1
            self.calls_started += 1
            self.maximum = max(self.maximum, self.active)
            if self.active >= self.limit:
                self.admitted.set()
        try:
            assert self.release.wait(3)
        finally:
            with self.lock:
                self.active -= 1

    def generate_text(self, *args, **kwargs):
        self.call()
        return LLMResponse(text='{"value": 1}')

    def generate_structured(self, *args, **kwargs):
        self.call()
        if self.repair:
            raise LLMStructuredOutputError("Needs formatting", response=LLMResponse(text="bad json"))
        return Answer(), LLMResponse(text='{"value": 1}')


def make_gateway(client, *, workers=4, local=False):
    return LLMGateway(client, LLMSettings(provider=ProviderName.OLLAMA if local else ProviderName.DEEPSEEK,
        privacy_mode=PrivacyMode.LOCAL_ONLY if local else PrivacyMode.CLOUD,
        discovery_workers=workers))


@pytest.mark.parametrize("workers,local,stateful", [(4, False, False), (2, False, False),
                                                     (1, False, False), (4, True, False), (4, False, True)])
def test_combined_text_structured_and_repair_calls_respect_gateway_limit(workers, local, stateful):
    limit = 1 if local or stateful else workers
    client = CountingClient(limit, repair=True)
    client.supports_concurrent_requests = not stateful
    gateway = make_gateway(client, workers=workers, local=local)
    ready = Barrier(9)
    def request(index):
        ready.wait(timeout=3)
        if index % 2:
            return gateway.generate_structured([], Answer, stage="semantic")
        return gateway.generate_text([], stage="presentation")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(request, index) for index in range(8)]
        ready.wait(timeout=3)
        try:
            assert client.admitted.wait(3)
            assert client.active == limit
        finally:
            client.release.set()
        for future in futures:
            future.result(timeout=3)
    assert client.maximum == limit
    assert client.active == 0
    assert client.calls_started == 12  # Four text calls and four structured + repair pairs.


@pytest.mark.parametrize("kind", ["text", "structured", "repair"])
def test_provider_failure_releases_slot_for_later_requests(kind):
    client = MockLLMClient()
    gateway = make_gateway(client, workers=1)
    def fail(*args, **kwargs):
        raise LLMTransportError("Synthetic request failed")
    if kind == "text":
        client.generate_text = fail
        request = lambda: gateway.generate_text([], stage="report")
    elif kind == "structured":
        client.generate_structured = fail
        request = lambda: gateway.generate_structured([], Answer, stage="report")
    else:
        def malformed(*args, **kwargs):
            raise LLMStructuredOutputError("Bad JSON", response=LLMResponse(text="bad"))
        client.generate_structured = malformed
        client.generate_text = fail
        request = lambda: gateway.generate_structured([], Answer, stage="report")
    with pytest.raises(LLMTransportError):
        request()
    client.generate_structured = lambda *args, **kwargs: (Answer(), LLMResponse(text='{"value":1}'))
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(gateway.generate_structured, [], Answer, stage="report").result(timeout=3) == Answer()


def test_cancelled_queued_request_never_reaches_provider():
    client = CountingClient(1)
    gateway = make_gateway(client, workers=1)
    cancelled = Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(gateway.generate_structured, [], Answer, stage="semantic")
        assert client.admitted.wait(3)
        queued = pool.submit(gateway.generate_structured, [], Answer, stage="presentation", cancelled=cancelled)
        cancelled.set()
        client.release.set()
        assert first.result(timeout=3) == Answer()
        with pytest.raises(CancelledError):
            queued.result(timeout=3)
    assert client.calls_started == 1


def test_cancellation_between_bad_format_and_repair_skips_repair():
    cancelled = Event()
    client = MockLLMClient()
    def bad(*args, **kwargs):
        cancelled.set()
        raise LLMStructuredOutputError("Bad JSON", response=LLMResponse(text="bad"))
    client.generate_structured = bad
    client.generate_text = lambda *args, **kwargs: pytest.fail("Cancelled repair reached provider")
    gateway = make_gateway(client, workers=1)
    with pytest.raises(CancelledError):
        gateway.generate_structured([], Answer, stage="presentation", cancelled=cancelled)


def test_cache_hits_need_no_provider_admission():
    client = MockLLMClient()
    gateway = make_gateway(client, workers=1)
    class Cache:
        def get_model(self, *args):
            return Answer()
    gateway.cache = Cache()
    with gateway._request_slots:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(gateway.generate_structured, [], Answer, stage="report").result(timeout=3) == Answer()
    assert client.calls == []
    assert gateway.usage[0]["cache_hit"]


def test_gateways_have_independent_capacity_and_session_usage():
    clients = [CountingClient(1), CountingClient(1)]
    gateways = [make_gateway(client, workers=1) for client in clients]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(gateway.generate_structured, [], Answer, stage="presentation") for gateway in gateways]
        try:
            assert all(client.admitted.wait(3) for client in clients), "A global gate blocked another session"
        finally:
            for client in clients:
                client.release.set()
        assert all(future.result(timeout=3) == Answer() for future in futures)
    assert gateways[0].usage is not gateways[1].usage
    assert all(len(gateway.usage) == 1 for gateway in gateways)
