import json
import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.test_retained_analysis_v216 import _linked_result, gateway, selection


def test_selection_format_repair_preserves_payload_and_still_requires_source_review():
    result = _linked_result()
    response = selection(result)
    valid = json.dumps(response)
    malformed = valid.replace('"ordered_insight_ids":', 'ordered_insight_ids":', 1)
    mock = gateway([malformed, valid])
    retained.select_retained_analysis(mock, result)
    assert retained.selected_record(result)['selection'] == response
    audit = json.loads(next(w.message for w in result.validation_warnings
                            if w.code=='retained_selection_format_repair'))
    assert audit['status'] == 'repaired' and audit['raw_response'] == malformed
    assert len(mock.client.calls) == 2
    assert not any(w.code=='presentation_retained_analysis_review' for w in result.validation_warnings)


@pytest.mark.parametrize('kind', ['changed_content', 'invalid_again'])
def test_format_repair_is_bounded_and_retains_failed_output(kind):
    result = _linked_result()
    valid = json.dumps(selection(result))
    malformed = valid.replace('"ordered_insight_ids":', 'ordered_insight_ids":', 1)
    repaired = valid.replace('Synthetic complete input coverage', 'Different content') if kind=='changed_content' else '{broken'
    mock = gateway([malformed, repaired])
    with pytest.raises(LLMResponseError):
        retained.select_retained_analysis(mock, result)
    assert retained.selected_record(result) is None and len(mock.client.calls) == 2
    audit = json.loads(next(w.message for w in result.validation_warnings
                            if w.code=='retained_selection_format_repair'))
    assert audit['status'] == 'failed'
    assert audit['raw_response'] == malformed and audit['repair_response'] == repaired
