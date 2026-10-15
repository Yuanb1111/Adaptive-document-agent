"""Reporting resumes distinguish retained evidence from new semantic responses.

External files are optional and remain outside the repository. Their historical
v142 verdicts predate the bound-review protocol: added identity fields below are
explicit synthetic transport adaptations, never new semantic approval. A missing
new response must stop the actual resume. Separate synthetic sources exercise
successful reporting and native PowerPoint export.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Lock

import pytest

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.services.pipeline_completion import is_complete
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
from tests.test_reporting_checkpoint_v142 import (
    RecordedResponseUnavailable, SchemaReplayClient, SyntheticReportingClient,
    _gateway, _payloads, _synthetic_checkpoint, _warnings,
)


SUPPORTED_EARLY_CHECKPOINT_VERSION = '2026-10-15-introduction-inventory-topic-recovery-v142'


def _bound_finding(payload, *, kind='meaning', part_id=None, meaning=None, reason='Synthetic source-bound protocol finding.'):
    """Bind fixture feedback to the exact supplied draft without choosing claims."""
    if kind == 'meaning':
        current = next(item for item in payload['current_meanings']
                       if part_id is None or item['part_id'] == part_id)
        return dict(kind=kind, part_id=current['part_id'], meaning_id=current['meaning_id'],
                    current_meaning=current['meaning'] if meaning is None else meaning,
                    source_quote=current['source_quote'], reason=reason)
    decision = next(item for item in payload['decisions']
                    if (item['part_id'] == part_id if part_id else item['include'] == (kind == 'included_part')))
    source = next(part for part in payload['source']['parts'] if part['id'] == decision['part_id'])
    return dict(kind=kind, part_id=decision['part_id'], meaning_id='', current_meaning='',
                source_quote=source['source_text'], reason=reason)


def _review(payload, *, accepted=False, scope='meanings', findings=None, reason='Synthetic independent source review.'):
    return dict(accepted=accepted, repair_scope=scope, reason=reason,
                selection_digest=payload['current_selection_digest'], findings=findings or [])


class EarlyCheckpointClient(SchemaReplayClient):
    """Use only retained early-stage outputs; unavailable futures fail closed."""
    supports_concurrent_requests = True

    def __init__(self, checkpoint, *, failure_kind):
        super().__init__()
        self.checkpoint, self.failure_kind = checkpoint, failure_kind
        self.intro = _warnings(checkpoint, 'company_introduction_summary_audit')[0]
        self.page_selection = _warnings(checkpoint, 'company_introduction_selection_audit')[0]['selection']
        self.audience_attempts = [item for item in self.intro['plan_audits']
                                  if 'introduction_audience_attempt' in item]
        self.calls, self.provenance, self.review_inputs, self.repair_inputs = [], [], [], []
        self.read_positions, self.review_position, self.repair_position = {}, 0, 0
        self._read_lock = Lock()

    def _response(self, schema, value, provenance):
        self.provenance.append(dict(operation=schema.__name__, provenance=provenance))
        typed = schema.model_validate(deepcopy(value))
        return typed, LLMResponse(text=typed.model_dump_json(),
            usage=LLMUsage(provider='mock', model='offline-retained-stage-artifact'))

    def _recorded_review(self, payload):
        position = self.review_position
        self.review_position += 1
        self.review_inputs.append(deepcopy(payload))
        if position >= len(self.audience_attempts):
            self.provenance.append(dict(operation='IntroductionAudienceReview',
                                        provenance='unavailable_new_bound_independent_review'))
            raise RecordedResponseUnavailable('No newly bound independent review was recorded')
        verdict = deepcopy(self.audience_attempts[position]['review'])
        # The historical boolean, reason and repair scope stay exact. Only the
        # new protocol envelope is synthetic and is labelled as such.
        ids = re.findall(r'summary_part_[a-z0-9]+', verdict['reason'])
        current_ids = {item['part_id'] for item in payload['current_meanings']}
        part_id = next(identifier for identifier in ids if identifier in current_ids)
        if position == 0:
            finding = _bound_finding(payload, part_id=part_id, reason=verdict['reason'])
            provenance = 'historical_verdict_with_synthetic_current_identity_envelope'
        else:
            # Preserve the stale original wording described by the recorded
            # second verdict. Do not pretend it is a defect of the new draft.
            original = next(item for item in self.audience_attempts[0]['decisions']
                            if item['part_id'] == part_id)
            current_texts = {item['meaning'] for item in payload['current_meanings']
                             if item['part_id'] == part_id}
            stale = next(item['meaning'] for item in original['required_meanings']
                         if item['meaning'] not in current_texts)
            finding = _bound_finding(payload, part_id=part_id, meaning=stale, reason=verdict['reason'])
            provenance = 'historical_verdict_with_synthetic_stale_identity_envelope'
        verdict.update(selection_digest=payload['current_selection_digest'], findings=[finding])
        return verdict, provenance

    def generate_structured(self, messages, response_model, **kwargs):
        schema, name = response_model, response_model.__name__
        self.calls.append(name)
        payloads = _payloads(messages)
        if name == 'IntroductionPages':
            return self._response(schema, self.page_selection, 'recorded_provider_response')
        if name == 'SummaryReadBatch':
            blocks = next(value for value in payloads if isinstance(value, list)
                          and value and 'block_id' in value[0])
            key = tuple(block['block_id'] for block in blocks)
            audit = next(record for record in self.intro['read_audits'] if tuple(record['block_ids']) == key)
            targeted = next((value for value in payloads if isinstance(value, dict)
                             and 'ranges' in value and 'rejected_parts' in value), None)
            if targeted is not None:
                attempt = audit['rejected_part_read']
                assert targeted['ranges'] == attempt['ranges']
                assert targeted['rejected_parts'] == attempt['rejected_parts']
                assert 'response' in attempt
                return self._response(schema, attempt['response'], 'recorded_targeted_reading_response')
            if any('Read ONLY the unassigned inclusive line ranges below.' in message['content'] for message in messages):
                attempt = audit['missing_range_read']
                assert 'response' in attempt
                return self._response(schema, attempt['response'], 'recorded_missing_range_reading_response')
            with self._read_lock:
                position = self.read_positions.get(key, 0)
                self.read_positions[key] = position + 1
            if position >= len(audit['attempts']):
                raise RecordedResponseUnavailable('No further initial reading response retained for this exact block inventory')
            attempt = audit['attempts'][position]
            if 'response' not in attempt:
                self.provenance.append(dict(operation=name, provenance='recorded_reading_schema_failure'))
                raise LLMStructuredOutputError('Retained reading response failed schema',
                    response=LLMResponse(text=attempt['raw_response'], usage=LLMUsage(
                        provider='mock', model='offline-retained-stage-artifact', finish_reason='stop')))
            return self._response(schema, attempt['response'], 'recorded_provider_response')
        if name == 'IntroductionAudienceSelection':
            # Audit decisions contain Python-bound evidence. The text is an
            # exact retained validated artifact, not an original raw response.
            decisions = deepcopy(self.audience_attempts[0]['decisions'])
            for decision in decisions:
                for meaning in decision['required_meanings']:
                    meaning.pop('proposed_source_quote', None)
            return self._response(schema, dict(decisions=decisions), 'retained_selection_artifact')
        if name == 'IntroductionAudienceReview':
            verdict, provenance = self._recorded_review(payloads[-1])
            return self._response(schema, verdict, provenance)
        if name == 'IntroductionMeaningRevision':
            self.repair_inputs.append((deepcopy(messages), kwargs.get('max_tokens')))
            self.repair_position += 1
            if self.failure_kind == 'capacity':
                if self.repair_position == 1:
                    usage = next(item for item in self.checkpoint.llm_usage
                                 if item['operation'] == 'IntroductionMeaningRevision')
                    assert usage['finish_reason'] == 'length' and usage['response_chars'] == 0
                    self.provenance.append(dict(operation=name,
                        provenance='recorded_16000_exhaustion_injected_as_new_budget_transport_fault'))
                    raise LLMStructuredOutputError('Recorded 16000-token exhaustion; not a new provider request',
                        response=LLMResponse(text='', usage=LLMUsage.model_validate(usage)))
                self.provenance.append(dict(operation=name, provenance='unavailable_new_capacity_response'))
                raise RecordedResponseUnavailable('The new larger-capacity response was never generated')
            revision = next(record['introduction_meaning_revision'] for record in self.intro['plan_audits']
                            if 'introduction_meaning_revision' in record)
            return self._response(schema, revision, 'recorded_provider_response')
        self.provenance.append(dict(operation=name, provenance='unavailable_never_generated_reporting_response'))
        raise RecordedResponseUnavailable('Early checkpoint never generated ' + name)


def _resume_after_recorded_background_failure(monkeypatch, checkpoint, raw, client):
    """Wait only at the real foreground validation boundary, changing no verdict.

    The adapter is an in-memory MockLLMClient with no SDK, credentials or network
    implementation. Non-local settings exercise genuine production concurrency.
    The barrier runs all real validators, then lets the recorded failing future
    finish before the existing nonblocking early-failure checkpoint inspects it.
    """
    from adaptive_document_agent.agent import company_introduction
    original_prepare = company_introduction.prepare_company_introduction
    prepared_instances, validations = [], []

    @contextmanager
    def capture_prepared(*args, **kwargs):
        with original_prepare(*args, **kwargs) as prepared:
            prepared_instances.append(prepared)
            yield prepared

    monkeypatch.setattr(company_introduction, 'prepare_company_introduction', capture_prepared)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.DEEPSEEK,
        model='offline-memory-adapter', discovery_workers=4))
    runner = DocumentOrchestrator(gateway)
    validate = runner._validate_analysis

    def validate_then_allow_background_finish(profile, observations, results):
        issues = validate(profile, observations, results)
        validations.append(deepcopy(issues))
        assert len(prepared_instances) == 1 and prepared_instances[0]._future is not None
        with pytest.raises(RecordedResponseUnavailable):
            prepared_instances[0]._future.result(timeout=60)
        return issues

    monkeypatch.setattr(runner, '_validate_analysis', validate_then_allow_background_finish)
    result = runner.analyse_pdf(raw, resume=checkpoint)
    assert len(validations) == 1
    assert all(issue in result.validation_warnings for issue in validations[0])
    assert prepared_instances[0]._pool is None
    return result


@pytest.mark.parametrize(('environment_key', 'failure_kind'), [
    ('ADA_REPORT_CAPACITY_CHECKPOINT', 'capacity'),
    ('ADA_REPORT_BINDING_CHECKPOINT', 'binding'),
])
def test_external_v142_early_checkpoint_reaches_only_available_review_boundary(monkeypatch, environment_key, failure_kind):
    filename = os.environ.get(environment_key)
    if not filename:
        pytest.skip('External retained early-reporting checkpoint not configured: ' + environment_key)
    path, pdf_path = Path(filename), Path(os.environ['ADA_REPORT_SOURCE_PDF'])
    original_bytes, raw = path.read_bytes(), pdf_path.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    source = PipelineResult.model_validate_json(original_bytes)
    assert source.pipeline_version == SUPPORTED_EARLY_CHECKPOINT_VERSION
    assert source.pipeline_state == 'partial' and source.retry_from == 'reporting'
    assert hashlib.sha256(raw).hexdigest() == source.document.sha256
    assert not source.insights and not source.charts and source.executive_brief is None
    original = source.model_copy(deep=True)
    retry = source.model_copy(deep=True)
    # Test fixture contract migration only; the production guard is untouched.
    # Both versions retain extraction-v19 and analysis-v74.
    retry.pipeline_version = PIPELINE_VERSION
    client = EarlyCheckpointClient(source, failure_kind=failure_kind)
    result = _resume_after_recorded_background_failure(monkeypatch, retry, raw, client)
    assert source == original and hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    assert hashlib.sha256(pdf_path.read_bytes()).hexdigest() == original.document.sha256
    assert result.document == original.document
    assert result.observations == original.observations
    assert result.analysis_results == original.analysis_results
    assert not is_complete(result) and result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    assert not result.insights and not result.charts and result.executive_brief is None
    assert any(issue.code == 'editorial_stages_skipped' for issue in result.validation_warnings)
    assert any(issue.code == 'company_introduction_unavailable' for issue in result.validation_warnings)
    assert not any(name in client.calls for name in ('InsightList', 'PresentationTopicSelection', 'ExecutiveBrief'))
    summary = _warnings(result, 'company_introduction_summary_audit')[0]
    assert summary['parts'] == client.intro['parts']
    assert not summary['audience_selection'] and summary['audience_part_ids'] is None
    if failure_kind == 'capacity':
        assert [limit for _, limit in client.repair_inputs] == [32000, 40000]
        assert client.repair_inputs[0][0] == client.repair_inputs[1][0]
        attempts = [row for row in summary['plan_audits'] if 'introduction_meaning_revision_attempt' in row]
        assert [row['status'] for row in attempts] == ['truncated', 'failed']
        assert attempts[0]['usage']['output_tokens'] == attempts[0]['usage']['reasoning_tokens'] == 16000
        assert attempts[0]['capacity_retry'] is True and attempts[1]['capacity_retry'] is False
    else:
        assert len(client.review_inputs) == 3
        assert len(client.review_inputs[1]['current_meanings']) == 20
        retained_meanings = [(decision['part_id'], meaning['meaning'])
            for decision in client.audience_attempts[1]['decisions'] for meaning in decision['required_meanings']]
        assert [(item['part_id'], item['meaning']) for item in client.review_inputs[1]['current_meanings']] == retained_meanings
        assert client.review_inputs[1]['current_meanings'] == client.review_inputs[2]['current_meanings']
        assert client.review_inputs[1]['decisions'] == client.review_inputs[2]['decisions']
        assert client.review_inputs[2]['review_binding_errors']
        assert any('introduction_meaning_revision' in row for row in summary['plan_audits'])
    from adaptive_document_agent.services.pptx_export import build_presentation
    with pytest.raises(ValueError, match='source-verified opening introduction'):
        build_presentation(result)


class SyntheticCapacityBindingClient(SyntheticReportingClient):
    """Synthetic meanings, explicit defects and mandatory independent verdicts."""

    def __init__(self, source, *, failure_mode=None):
        super().__init__(source, accept_introduction=True)
        self.failure_mode = failure_mode
        self.review_inputs, self.repair_inputs, self.addition_inputs = [], [], []
        self.repair_count, self.review_count = 0, 0
        self.original_bundle, self.first_part, self.omitted_part = None, None, None
        self.before_addition = None

    def _typed(self, schema, value):
        typed = schema.model_validate(value)
        return typed, LLMResponse(text=typed.model_dump_json(),
            usage=LLMUsage(provider='mock', model='synthetic-v143-reporting'))

    def generate_structured(self, messages, response_model, **kwargs):
        schema, name = response_model, response_model.__name__
        values = _payloads(messages)
        if name not in {'IntroductionAudienceSelection', 'IntroductionAudienceReview',
                        'IntroductionMeaningRevision', 'IntroductionAudienceSelectionAddition', 'SummarySynthesisDraft'}:
            return super().generate_structured(messages, response_model, **kwargs)
        self.calls.append(name)
        if name == 'IntroductionAudienceSelection':
            parts = values[0]['parts']
            assert len(parts) == 3
            self.first_part, self.omitted_part = parts[0]['id'], parts[-1]['id']
            self.original_bundle = parts[0]['source_text'].strip()
            self.decisions = [dict(part_id=part['id'], include=index < 2,
                reason='The synthetic business and delivery prerequisite are central.' if index < 2
                else 'Synthetic initial omission for independently reviewed correction.',
                required_meanings=[dict(meaning=part['source_text'].strip())] if index < 2 else [])
                for index, part in enumerate(parts)]
            return self._typed(schema, dict(decisions=self.decisions))
        if name == 'IntroductionMeaningRevision':
            self.repair_count += 1
            self.repair_inputs.append((deepcopy(messages), kwargs.get('max_tokens')))
            if self.repair_count == 1 or self.failure_mode == 'capacity_exhausted':
                raise LLMStructuredOutputError('Explicit synthetic reasoning/output capacity fault',
                    response=LLMResponse(text='', usage=LLMUsage(provider='mock', model='synthetic-v143',
                        output_tokens=16000, reasoning_tokens=16000, finish_reason='length')))
            payload = values[-1]
            edits = [dict(meaning_id=item['meaning_id'], required_meanings=[
                dict(meaning='We provide scheduling software for operating teams.'),
                dict(meaning='We charge annual subscription fees.')]
                if item['part_id'] == self.first_part else [dict(meaning=item['meaning'])])
                for item in payload['original_meanings']]
            return self._typed(schema, dict(edits=edits))
        if name == 'IntroductionAudienceReview':
            self.review_count += 1
            payload = values[-1]
            self.review_inputs.append(deepcopy(payload))
            if self.review_count == 1:
                finding = _bound_finding(payload, part_id=self.first_part,
                    reason='The synthetic product and pricing assertions must be independently checkable.')
                value = _review(payload, findings=[finding],
                    reason='Split the synthetic product and pricing assertions, preserving both.')
            elif self.review_count == 2 or self.failure_mode == 'stale_exhausted':
                finding = _bound_finding(payload, part_id=self.first_part, meaning=self.original_bundle,
                    reason='Explicit synthetic stale feedback about the original bundled assertion.')
                value = _review(payload, findings=[finding], reason='The original bundled assertion remains bundled.')
            elif self.review_count == 3:
                self.before_addition = deepcopy(payload['decisions'])
                finding = _bound_finding(payload, kind='omitted_part', part_id=self.omitted_part,
                    reason='The synthetic geographic service limit is essential to interpreting the business.')
                value = _review(payload, scope='selection', findings=[finding],
                    reason='Include the source geographic scope limitation without removing existing assertions.')
            elif self.failure_mode == 'addition_rejected':
                finding = _bound_finding(payload, part_id=self.omitted_part,
                    reason='The independent negative fixture rejects the new wording.')
                value = _review(payload, findings=[finding], reason='The independent fixture withholds final acceptance.')
            else:
                value = _review(payload, accepted=True, scope='selection',
                    reason='All four source assertions and the geographic restriction are retained faithfully.')
            return self._typed(schema, value)
        if name == 'IntroductionAudienceSelectionAddition':
            payload = values[-1]
            self.addition_inputs.append(deepcopy(payload))
            assert payload['allowed_part_ids'] == [self.omitted_part]
            part = next(part for part in payload['source']['parts'] if part['id'] == self.omitted_part)
            decisions = [dict(part_id=self.omitted_part, include=True,
                reason='The independently identified service scope limitation is essential.',
                required_meanings=[dict(meaning=part['source_text'].strip())])]
            if self.failure_mode == 'addition_changes_protected_inventory':
                # A well-typed response cannot smuggle a previously included
                # owner into an addition or erase its already split assertions.
                decisions.append(dict(part_id=self.first_part, include=False,
                    reason='Synthetic forbidden attempt to replace protected included claims.', required_meanings=[]))
            return self._typed(schema, dict(decisions=decisions))
        parts = values[0]['parts']
        value = dict(pages=[dict(title='Software, delivery and scope', items=[dict(label='Business and service scope',
            text=' '.join(meaning['meaning'] for part in parts for meaning in part['required_meanings']),
            fact_ids=[fact['id'] for part in parts for fact in part['facts']])])])
        return self._typed(schema, value)


@pytest.mark.parametrize('failure_mode', [None, 'capacity_exhausted', 'stale_exhausted',
    'addition_rejected', 'addition_changes_protected_inventory'])
def test_synthetic_whole_reporting_capacity_binding_and_addition_keep_export_gate(monkeypatch, failure_mode):
    from adaptive_document_agent.agent.introduction_selection_addition import IntroductionAudienceSelectionAddition
    source, raw = _synthetic_checkpoint()
    source.document.pages[1].text = (
        'SUMMARY\nWe provide scheduling software for operating teams and charge annual subscription fees.\n'
        'Staff training is required before service delivery.\n'
        'The scheduling service is available only in the home market.\n')
    original = source.model_copy(deep=True)
    client = SyntheticCapacityBindingClient(source, failure_mode=failure_mode)
    client.additional_schemas = {'IntroductionAudienceSelectionAddition': IntroductionAudienceSelectionAddition}
    gateway = _gateway(client)
    # Stateful local fixtures deliberately exercise the real deferred-attach
    # branch. Concurrent early-stop wiring is covered by the external replays.
    assert gateway.discovery_workers == 1
    runner = DocumentOrchestrator(gateway)
    monkeypatch.setattr(runner, '_load_document', lambda data, digest:
        source.document if data == raw and digest == source.document.sha256 else pytest.fail('Wrong source boundary'))
    result = runner.analyse_pdf(raw, resume=source)
    assert source == original
    assert result.observations == original.observations and result.analysis_results == original.analysis_results
    assert result.executive_brief is not None and result.presentation_plan.planning_origin == 'topic_compilation'
    assert not any(issue.code == 'presentation_plan_fallback' for issue in result.validation_warnings)
    assert [limit for _, limit in client.repair_inputs] == [32000, 40000]
    assert client.repair_inputs[0][0] == client.repair_inputs[1][0]
    summary = _warnings(result, 'company_introduction_summary_audit')[0]
    assert len(summary['parts']) == 4 and len([part for part in summary['parts'] if part['role'] == 'content']) == 3
    assert client.calls.count('IntroductionMeaningRevision') == 2
    from adaptive_document_agent.services.pptx_export import build_presentation
    if failure_mode is None:
        assert is_complete(result)
        assert len(client.review_inputs) == 4 and len(client.addition_inputs) == 1
        assert client.review_inputs[1]['current_meanings'] == client.review_inputs[2]['current_meanings']
        assert client.review_inputs[2]['review_binding_errors']
        final = client.review_inputs[3]
        previous = {item['part_id']: item for item in client.before_addition if item['include']}
        assert {item['part_id']: item for item in final['decisions'] if item['part_id'] in previous} == previous
        assert len(final['current_meanings']) == 4
        assert all(item['include'] for item in final['decisions'])
        assert summary['audience_selection']['independent_review']['accepted'] is True
        assert build_presentation(result).startswith(b'PK')
    else:
        assert not is_complete(result) and result.pipeline_state == 'partial'
        assert not summary['audience_selection'] and summary['audience_part_ids'] is None
        assert 'SummarySynthesisDraft' not in client.calls
        if failure_mode == 'capacity_exhausted':
            assert len(client.review_inputs) == 1 and not client.addition_inputs
        elif failure_mode == 'stale_exhausted':
            assert len(client.review_inputs) == 3 and not client.addition_inputs
        elif failure_mode == 'addition_rejected':
            assert len(client.review_inputs) == 4 and len(client.addition_inputs) == 1
        else:
            assert len(client.review_inputs) == 3 and len(client.addition_inputs) == 1
        with pytest.raises(ValueError, match='source-verified opening introduction'):
            build_presentation(result)
