"""Exercise length recovery through the real adapter, gateway, cache and scorer."""

import ast
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.value_scorer import AnalysisValueScorer
from adaptive_document_agent.models.customization import ReportRequirement, ReportRequirements
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.config import PrivacyMode
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_candidate_scoring_batches import BatchClient, score_fixture


@pytest.mark.parametrize('provider', [ProviderName.DEEPSEEK, ProviderName.OLLAMA])
@pytest.mark.parametrize('customized', [False, True])
def test_repeated_length_failures_reach_singletons_without_losing_decisions(
    monkeypatch, tmp_path, provider, customized,
):
    candidates, index, profile, client, baseline_gateway = score_fixture(41)
    if customized:
        profile.report_requirements = ReportRequirements(
            original_request='正文中文；附录完整保留表格',
            items=[ReportRequirement(id='language', kind='output_language',
                request_quote='正文中文', description='Chinese body', language='Chinese')],
        )
    source_before = [c.model_dump() for c in candidates]
    profile_before = profile.model_dump()
    expected = AnalysisValueScorer(baseline_gateway).score(candidates, index, profile)
    settings = LLMSettings(provider=provider, model='deepseek-flash', discovery_workers=1,
        privacy_mode=PrivacyMode.LOCAL_ONLY if provider == ProviderName.OLLAMA else PrivacyMode.CLOUD)
    adapter = LiteLLMProvider(settings)
    calls = []

    def complete(messages, **kwargs):
        ids = ast.literal_eval(messages[-1]['content'].split(': ', 1)[1])
        calls.append(ids)
        assert kwargs['max_tokens'] == 12000
        if provider == ProviderName.DEEPSEEK:
            assert kwargs['extra_body']['thinking']['type'] == 'disabled'
        else:
            assert 'extra_body' not in kwargs  # Local routing keeps its own policy.
        wire = ast.literal_eval(next(m['content'] for m in messages
            if m['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>'))
            .split('\n', 1)[1].rsplit('\n', 1)[0])
        assert len(wire['candidates']) == 41  # Comparison context survives every split.
        response = deepcopy(client.payload)
        response['scores'] = [d for d in response['scores'] if d['candidate_id'] in ids]
        truncated = len(ids) > 1
        if truncated:
            # Even valid JSON under a length finish must be discarded, not salvaged.
            for decision in response['scores']:
                decision.update(score=1, rejected=False, reasons=['Unfinished decision'])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(response)), finish_reason='length' if truncated else 'stop')],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=12000 if truncated else 100))

    monkeypatch.setattr(adapter, '_completion', complete)
    gateway = LLMGateway(adapter, settings, cache=DiskCache(tmp_path))
    actual = AnalysisValueScorer(gateway).score(candidates, index, profile)
    assert [s.model_dump(exclude={'semantic_audit'}) for s in actual] == [
        s.model_dump(exclude={'semantic_audit'}) for s in expected]
    assert [c.model_dump() for c in candidates] == source_before
    assert profile.model_dump() == profile_before
    assert len(calls) == 80  # 2*n-1 for the first 40, plus the final singleton.
    assert len([ids for ids in calls if len(ids) == 1]) == 41
    audit = actual[0].semantic_audit.response_audit.batches
    assert len(audit) == 80
    assert sum(bool(a.error) for a in audit) == 39
    assert all(not a.scores and a.output_tokens == 12000 for a in audit if a.error)
    assert all('chunk_id' in row and 'recovery_depth' in row for row in gateway.usage)
    assert max(row['recovery_depth'] for row in gateway.usage) == 6
    assert not any(row['status'] == 'format_repair' for row in gateway.usage)
    # A user retry can reuse every successful child, including rejected decisions.
    before_calls = len(calls)
    assert AnalysisValueScorer(gateway).score(candidates, index, profile) == actual
    assert len(calls) - before_calls == 39  # Only unsuccessful parent calls repeat.
    assert sum(bool(row.get('cache_hit')) for row in gateway.usage) == 41


def test_invalid_format_is_not_misclassified_as_length_recovery():
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    from adaptive_document_agent.services.llm.usage import LLMUsage

    candidates, _, profile, client, gateway = score_fixture(40)

    class InvalidClient(BatchClient):
        def generate_structured(self, messages, response_model, **kwargs):
            self.calls.append(messages)
            raise LLMStructuredOutputError('Invalid schema', response=LLMResponse(
                text='invalid', usage=LLMUsage(provider='mock', model='mock', finish_reason='stop')))

    gateway.client = InvalidClient(client.payload)
    # Exercise scorer dispatch directly: format errors belong to the gateway's
    # existing one-repair policy, never to candidate batch splitting.
    class NoRepairGateway:
        def generate_structured(self, *args, **kwargs):
            return gateway.client.generate_structured(*args, **kwargs)

    with pytest.raises(LLMStructuredOutputError, match='Invalid schema'):
        AnalysisValueScorer(NoRepairGateway())._semantic_batches(candidates, profile)
    assert len(gateway.client.calls) == 1
