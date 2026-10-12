"""Cloud writing overlaps bounded batches without changing evidence or order."""
from threading import Barrier, Event, Lock, get_ident

import pytest

from adaptive_document_agent.agent.insight_generator import InsightGenerator
from tests.test_insight_batch_recovery import BatchClient, gateway, results


def test_cloud_batches_overlap_and_cache_preserves_source_order(tmp_path):
    barrier, lock = Barrier(2), Lock()
    active = peak = 0
    class Client(BatchClient):
        supports_concurrent_requests = True
        def generate_structured(self, *args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(5)
                return super().generate_structured(*args, **kwargs)
            finally:
                with lock:
                    active -= 1
    client = Client()
    routed = gateway(client, tmp_path, local=False)
    generated = InsightGenerator(routed).generate(results(24))
    assert peak == 2 and active == 0
    assert [i.result_ids[0] for i in generated] == [f'r{i}' for i in range(24)]
    assert all(i.evidence[0].page == n+1 for n,i in enumerate(generated))
    assert InsightGenerator(routed).generate(results(24)) == generated
    assert len(client.records) == 4 and sum(r.get('cache_hit',False) for r in routed.usage) == 4


@pytest.mark.parametrize('local,concurrent', [(True,True),(False,False)])
def test_local_and_stateful_clients_keep_serial_caller_order(local, concurrent):
    threads = []
    class Client(BatchClient):
        supports_concurrent_requests = concurrent
        def generate_structured(self, *args, **kwargs):
            threads.append(get_ident())
            return super().generate_structured(*args, **kwargs)
    client = Client()
    InsightGenerator(gateway(client, local=local)).generate(results(13))
    assert threads == [get_ident()] * 3
    assert client.records[-1][0] == ('r12',)


def test_parallel_privacy_failure_cancels_pending_work_and_retains_original_error():
    import json
    from concurrent.futures import CancelledError
    from adaptive_document_agent.agent.insight_batches import generate_batches
    from adaptive_document_agent.agent.insight_generator import InsightList
    from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
    first_started = Event()
    calls = []
    class Gateway:
        discovery_workers = 4
        def generate_structured(self, messages, schema, *, cancelled, **kwargs):
            rows = json.loads(messages[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0])
            calls.append(rows[0]['task_id'])
            if rows[0]['task_id'] == 'r0':
                first_started.set()
                assert cancelled.wait(5)
                raise CancelledError('Neighbour cancelled')
            assert first_started.wait(5)
            raise PrivacyViolationError('Original endpoint rejection')
    with pytest.raises(PrivacyViolationError, match='Original endpoint rejection'):
        list(generate_batches(Gateway(), [r.model_dump() for r in results(24)], InsightList, 'Read evidence'))
    assert set(calls) == {'r0','r6'}
