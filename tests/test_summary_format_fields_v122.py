import json

import pytest
from pydantic import BaseModel, Field, ValidationError

from adaptive_document_agent.agent.summary_draft_protocol import author_draft
from adaptive_document_agent.agent.summary_format_fields import (
    SummaryStringRepairs, string_failure_context, apply_string_repairs)
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError


class Draft(BaseModel):
    text: str = Field(max_length=600)
    fact_ids: list[str]


def test_601_character_field_is_repaired_without_regenerating_other_fields():
    original = {'text': 'service ' * 74 + 'requires.', 'fact_ids': ['f0', 'f1']}
    assert len(original['text']) == 601
    shortened = original['text'].replace('service ', '', 1)
    class Client:
        calls = []
        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(schema)
            if schema is Draft:
                raw = json.dumps(original)
                try:
                    Draft.model_validate_json(raw)
                except ValidationError as exc:
                    raise LLMStructuredOutputError('Too long', response=LLMResponse(text=raw)) from exc
            assert issubclass(schema, SummaryStringRepairs)
            return schema(replacements=[{'path': 'text', 'value': shortened}])
    audit, client = {}, Client()
    result = author_draft(client, [], Draft, audit)
    assert result.text == shortened and result.fact_ids == original['fact_ids']
    assert client.calls[0] is Draft and issubclass(client.calls[1], SummaryStringRepairs)
    assert audit['draft_format_attempts'][-1]['repair_kind'] == 'targeted_strings'


def test_patch_cannot_change_evidence_ids_or_repeat_a_path():
    raw = json.dumps({'text': 'x' * 601, 'fact_ids': ['f0']})
    data, paths, _ = string_failure_context(raw, Draft)
    for replacements in ([{'path': 'fact_ids.0', 'value': 'f9'}],
                         [{'path': 'text', 'value': 'ok'}, {'path': 'text', 'value': 'ok'}]):
        with pytest.raises(ValueError, match='exactly the failing'):
            apply_string_repairs(data, paths, SummaryStringRepairs(replacements=replacements), Draft)
    assert data['text'] == 'x' * 601 and data['fact_ids'] == ['f0']


def test_union_model_labels_resolve_to_actual_json_field_paths():
    from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft
    raw = json.dumps({'pages': [{'placement': 'body', 'title': 'Services', 'items': [
        {'label': 'Scope', 'text': 'x' * 6001, 'fact_ids': ['f0']}]}]})
    data, paths, fields = string_failure_context(raw, SummarySynthesisDraft)
    assert set(paths) == {'pages.0.items.0.text'}
    assert fields[0]['maximum_characters'] == 6000
    result = apply_string_repairs(data, paths, SummaryStringRepairs(replacements=[
        {'path': 'pages.0.items.0.text', 'value': 'Supported scope.'}]), SummarySynthesisDraft)
    assert result.pages[0].placement == 'body'
    assert result.pages[0].items[0].fact_ids == ['f0']


def test_large_overflow_still_requires_structural_split_repair():
    assert string_failure_context(json.dumps({'text': 'x' * 1200, 'fact_ids': ['f0']}), Draft) is None


def test_appendix_union_alternative_does_not_block_targeted_field_repair():
    from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft
    raw = json.dumps({'pages': [
        {'placement': 'body', 'title': 'Scope', 'items': [
            {'label': 'Business', 'text': 'x' * 6001, 'fact_ids': ['f0']}]},
        {'placement': 'appendix', 'title': 'Supporting detail', 'items': [
            {'label': 'Evidence', 'text': 'x' * 6001, 'fact_ids': ['f1']} for _ in range(9)]}]})
    data, paths, fields = string_failure_context(raw, SummarySynthesisDraft)
    assert len(fields) == 10
    assert {f['maximum_characters'] for f in fields} == {6000}
    result = apply_string_repairs(data, paths, SummaryStringRepairs(replacements=[
        {'path': f['path'], 'value': 'Supported complete detail.'} for f in fields]), SummarySynthesisDraft)
    assert len(result.pages[1].items) == 9
    assert result.pages[1].placement == 'appendix'
    assert all(item.fact_ids == ['f1'] for item in result.pages[1].items)


def test_string_patch_schema_rejects_overruns_before_applying_patch():
    from adaptive_document_agent.agent.summary_format_fields import string_repair_schema
    schema = string_repair_schema([
        {'path': 'pages.0.items.0.text', 'maximum_characters': 280},
        {'path': 'pages.1.items.0.text', 'maximum_characters': 1200}])
    with pytest.raises(ValidationError):
        schema(replacements=[{'path': 'pages.0.items.0.text', 'value': 'x' * 281},
                             {'path': 'pages.1.items.0.text', 'value': 'valid'}])
    assert schema(replacements=[{'path': 'pages.0.items.0.text', 'value': 'valid'},
                               {'path': 'pages.1.items.0.text', 'value': 'x' * 1200}])
