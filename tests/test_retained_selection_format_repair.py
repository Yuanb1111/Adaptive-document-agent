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


@pytest.mark.parametrize('nested', [False, True])
def test_forbidden_null_placeholder_is_removed_without_a_model_rewrite(nested):
    result = _linked_result()
    response = selection(result)
    malformed = json.loads(json.dumps(response))
    (malformed['decisions'][0] if nested else malformed)['unused'] = None
    mock = gateway([malformed])
    retained.select_retained_analysis(mock, result)
    assert retained.selected_record(result)['selection'] == response
    assert len(mock.client.calls) == 1
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'retained_selection_format_repair'))
    assert audit['repair_method'] == 'remove_forbidden_null_fields'
    assert audit['removed_null_paths'] == ([['decisions', 0, 'unused']] if nested else [['unused']])
    assert json.loads(audit['raw_response']) == malformed
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)


@pytest.mark.parametrize('extra', [0, False, '', [], {}, 'unsupported fact'])
def test_non_null_extra_content_cannot_be_discarded_by_format_repair(extra):
    result = _linked_result()
    response = selection(result)
    malformed = dict(response, unused=extra)
    mock = gateway([malformed, response])
    with pytest.raises(LLMResponseError):
        retained.select_retained_analysis(mock, result)
    assert len(mock.client.calls) == 2
    assert retained.selected_record(result) is None


def test_null_placeholder_does_not_allow_missing_required_content():
    from adaptive_document_agent.services.llm.structured import repair_extra_null_fields
    malformed = dict(selection(_linked_result()), unused=None)
    del malformed['ordered_insight_ids']
    assert repair_extra_null_fields(json.dumps(malformed), retained.SourceAuthoredAnalysisSelection) is None


def test_duplicate_keys_cannot_be_silently_normalized_with_null_fields():
    from adaptive_document_agent.services.llm.structured import repair_extra_null_fields
    malformed = json.dumps(dict(selection(_linked_result()), unused=None))
    malformed = malformed.replace('"unused": null', '"unused": "source claim", "unused": null')
    assert repair_extra_null_fields(malformed, retained.SourceAuthoredAnalysisSelection) is None


def test_declared_null_field_is_preserved_when_removing_an_extra_null():
    from adaptive_document_agent.services.llm.structured import repair_extra_null_fields
    original = dict(selection(_linked_result()), unused=None)
    original['decisions'][0]['page'] = None
    # Legacy selections permit an absent authored page. Source-authored include
    # decisions now require it; a null there must not become a successful repair.
    repaired, paths = repair_extra_null_fields(json.dumps(original), retained.RetainedAnalysisSelection)
    assert paths == [['unused']]
    assert 'page' in repaired.decisions[0].model_fields_set and repaired.decisions[0].page is None


def test_recorded_null_field_failure_is_repaired_without_rewriting_content():
    import os
    from pathlib import Path
    from adaptive_document_agent.models import PipelineResult
    from adaptive_document_agent.agent.retained_selection_request import selection_request
    path = os.environ.get('ADA_SELECTION_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_SELECTION_DIAGNOSTIC to a private recorded format failure')
    result = PipelineResult.model_validate_json(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'retained_selection_format_repair'))
    original = json.loads(audit['raw_response'])
    mock = gateway([original])
    repaired = selection_request(mock, [], retained.SourceAuthoredAnalysisSelection, result, 0)
    repaired_audit = json.loads(result.validation_warnings[-1].message)
    expected = json.loads(audit['raw_response'])
    for path in repaired_audit['removed_null_paths']:
        parent = expected
        for key in path[:-1]:
            parent = parent[key]
        assert parent.pop(path[-1]) is None
    assert repaired.model_dump(exclude_unset=True) == expected
    assert len(mock.client.calls) == 1
