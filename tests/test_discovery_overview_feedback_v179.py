"""Overview retries must correct exact errors and keep terminal failures inspectable."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.document_discovery import DocumentDiscovery
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_discovery_overview_contract import source_chunks
from tests.test_interrupted_analysis_reruns import flow, run


@pytest.mark.parametrize('invalid,path,kind', [
    ({'document_summary': 'PRIVATE_SOURCE_SENTINEL ' * 60}, ['document_summary'], 'string_too_long'),
    ({'document_summary_pages': ['2-4']}, ['document_summary_pages', 0], 'int_type'),
    ({'overview_points': ['a', 'b', 'c', 'd']}, ['overview_points'], 'too_long'),
    ({'metrics': ['PRIVATE_SOURCE_SENTINEL']}, ['metrics'], 'extra_forbidden'),
])
def test_exact_field_constraints_reach_retry_without_repeating_invalid_source_content(invalid, path, kind):
    chunks, discoveries = source_chunks()
    original = deepcopy((chunks, discoveries))
    client = MockLLMClient([invalid, {'document_summary': 'Supported overview.', 'document_summary_pages': [2]}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    value = DocumentDiscovery(gateway)._synthesize_overview(chunks, discoveries, None)
    assert value.document_summary_pages == [2]
    assert len(client.calls) == 2
    assert client.calls[1][:len(client.calls[0])] == client.calls[0]
    feedback = json.loads(client.calls[1][-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert feedback['validation_errors'][0]['loc'] == path
    assert feedback['validation_errors'][0]['type'] == kind
    assert 'PRIVATE_SOURCE_SENTINEL' not in json.dumps(client.calls[1])
    assert (chunks, discoveries) == original


def terminal_failure():
    chunks, discoveries = source_chunks()
    invalid = {'document_summary_pages': ['PRIVATE_SOURCE_SENTINEL']}
    client = MockLLMClient([invalid, invalid])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    with pytest.raises(LLMStructuredOutputError) as caught:
        DocumentDiscovery(gateway)._synthesize_overview(chunks, discoveries, None)
    assert len(client.calls) == 2
    return caught.value


def test_terminal_error_has_field_path_and_two_raw_responses_but_no_source_in_public_message(caplog):
    failure = terminal_failure()
    assert 'document_summary_pages.0 (int_type)' in str(failure)
    assert 'after 2 attempts' in str(failure)
    assert 'PRIVATE_SOURCE_SENTINEL' not in str(failure)
    assert 'PRIVATE_SOURCE_SENTINEL' not in caplog.text
    diagnostics = failure.diagnostics
    assert diagnostics['stage'] == 'discovery'
    assert len(diagnostics['attempts']) == 2
    assert all('PRIVATE_SOURCE_SENTINEL' in row['raw_response'] for row in diagnostics['attempts'])
    assert 'input' not in diagnostics['attempts'][0]['schema_errors'][0]
    json.dumps(diagnostics)


def test_worker_publishes_diagnostic_download_without_restarting_or_caching_failed_analysis(flow):
    failure = terminal_failure()
    flow.orchestrator.analyse_pdf.side_effect = failure
    assert run(flow) is None
    assert run(flow) is None
    assert flow.orchestrator.analyse_pdf.call_count == 1
    saved = flow.st.session_state['analysis_failure']
    assert saved['diagnostics'] == failure.diagnostics
    assert json.loads(flow.st.download_button.call_args.args[1]) == failure.diagnostics
    assert flow.st.download_button.call_args.args[2] == 'analysis_failure_diagnostics.json'
    assert flow.st.download_button.call_args.kwargs['on_click'] == 'ignore'
    assert 'analysis-result-same-scope' not in flow.cache_values
