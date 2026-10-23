"""Full reporting retries with explicit recorded, synthetic and unavailable boundaries.

The optional external checkpoint test never ships document data in this repository.
Set ADA_REPORT_CHECKPOINT and ADA_REPORT_SOURCE_PDF to replay a retained v141
checkpoint. It intentionally cannot approve an introduction whose provider
selection and independent verdict were not retained in that export.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.models import DocumentPage, PipelineResult
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.services.pipeline_completion import is_complete
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION


SUPPORTED_RECORDED_VERSION = "2026-10-15-meaning-capacity-source-headers-v141"


class RecordedResponseUnavailable(LLMResponseError):
    """A missing historical response is not an independent model acceptance."""


def _payloads(messages):
    values = []
    for message in messages:
        content = message['content']
        if not content.startswith('<UNTRUSTED_DOCUMENT_CONTENT>'):
            continue
        try:
            value = json.loads(content.split('\n', 1)[1].rsplit('\n', 1)[0])
            if isinstance(value, dict) and 'current_selection_digest' in value:
                from tests.introduction_review_helpers import materialize_review_wire
                value = materialize_review_wire(value)
            values.append(value)
        except (ValueError, IndexError):
            continue
    return values


def _warnings(checkpoint, code):
    return [json.loads(issue.message) for issue in checkpoint.validation_warnings if issue.code == code]


def _gateway(client):
    # The actual gateway, privacy, response and cache boundaries remain active.
    # This local adapter has no credentials or network-capable implementation.
    return LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model='offline-report-checkpoint'))


def _decisions(parts):
    """Synthetic protocol proposal only; it cannot grant semantic approval."""
    included = next(part['id'] for part in parts if 8 <= len(part['source_text'].strip()) <= 2000)
    return [dict(part_id=part['id'], include=part['id'] == included,
        reason='Synthetic transport fixture; independent semantic review remains mandatory.',
        required_meanings=[dict(meaning=part['source_text'].strip())] if part['id'] == included else [])
        for part in parts]


def _synthetic_meaning_refs(parts, text):
    """Explicit author mappings for exact synthetic meaning text only."""
    return [dict(part_id=part['id'], meaning_index=index)
            for part in parts for index, meaning in enumerate(part.get('required_meanings', []))
            if meaning['meaning'] in text]


class SchemaReplayClient(MockLLMClient):
    """Honor the gateway's bounded text protocol without skipping its parser."""

    def generate_text(self, messages, *, temperature=0, max_tokens=None, model=None):
        from adaptive_document_agent.agent.introduction_audience import (
            IntroductionAudienceSelection, IntroductionAudienceReview,
        )
        from adaptive_document_agent.agent.introduction_selection_inventory import IntroductionAudienceInventoryCorrection
        from adaptive_document_agent.agent.introduction_meaning_repair import IntroductionMeaningRevision
        from adaptive_document_agent.agent.topic_coverage_review import TopicCoverageReview
        from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
        prefix = 'Return only JSON matching this schema: '
        assert messages[0]['content'].startswith(prefix)
        assert max_tokens is not None and max_tokens > 0
        title = json.loads(messages[0]['content'][len(prefix):])['title']
        schemas = {schema.__name__: schema for schema in (
            IntroductionAudienceSelection, IntroductionAudienceReview,
            IntroductionAudienceInventoryCorrection, IntroductionMeaningRevision, TopicCoverageReview,
            BriefClaimDirectionReview,
        )}
        # Subclasses can add a newly introduced protocol without bypassing the
        # real gateway's schema-text parser or changing the v142 replay contract.
        schemas.update(getattr(self, 'additional_schemas', {}))
        _, response = self.generate_structured(messages[1:], schemas[title],
            temperature=temperature, max_tokens=max_tokens, model=model)
        return response


class CheckpointClient(SchemaReplayClient):
    """Replay retained evidence responses; never fabricate missing review approval."""

    def __init__(self, checkpoint):
        super().__init__()
        self.checkpoint = checkpoint
        self.calls, self.provenance, self.review_inputs = [], [], []
        self.intro = _warnings(checkpoint, 'company_introduction_summary_audit')[0]
        self.selection = _warnings(checkpoint, 'company_introduction_selection_audit')[0]['selection']
        self.coverage = _warnings(checkpoint, 'presentation_topic_coverage_unresolved')[0]
        self.read_positions, self.coverage_position = {}, 0
        self.synthetic_decisions = None

    def _response(self, schema, value, provenance):
        self.provenance.append(dict(operation=schema.__name__, provenance=provenance))
        from tests.summary_author_helpers import writer_test_value
        typed = schema.model_validate(writer_test_value(schema, deepcopy(value)))
        return typed, LLMResponse(text=typed.model_dump_json(),
            usage=LLMUsage(provider='mock', model='offline-recorded-artifact'))

    def _meaning_response(self, pending, schema):
        """Reindex recorded accepted verdicts only for the unchanged saved brief.

        Literal evidence catalogs, full item fields and every comparison claim
        must match. Ref-to-context expansion is transport adaptation, not a new
        verdict. An absent match remains unavailable.
        """
        saved = self.checkpoint.executive_brief
        audits = _warnings(self.checkpoint, 'executive_brief_meaning_audit')
        verdicts = []
        for row in pending:
            item = row['item']
            known = [candidate for candidate in saved.items if
                candidate.model_dump(mode='json', exclude={'evidence'}) ==
                {key: value for key, value in item.items() if key != 'evidence'}]
            if len(known) != 1:
                raise RecordedResponseUnavailable('No unchanged recorded briefing item for this request')
            texts = {quote['text'] for quote in item['evidence']}
            match = None
            for audit in audits:
                for value in audit['response']['items']:
                    old_index = str(value['index'])
                    catalog = audit['source_catalogs'].get(old_index, {})
                    if (value['accepted'] and old_index not in audit['errors']
                            and set(catalog.values()) == texts
                            and all(comparison['claim'] in item['text'] for comparison in value['comparisons'])):
                        match = deepcopy(value)
                        match['index'] = row['index']
                        for comparison in match['comparisons']:
                            for end in ('start', 'end'):
                                reference = comparison[end + '_ref']
                                if reference:
                                    comparison[end + '_context'] = catalog[reference]
                                    comparison[end + '_ref'] = ''
                        break
                if match is not None:
                    break
            if match is None:
                raise RecordedResponseUnavailable('No matching recorded accepted briefing verdict')
            verdicts.append(match)
        return self._response(schema, dict(items=verdicts), 'recorded_verdict_transport_reindex')

    def generate_structured(self, messages, response_model, **kwargs):
        schema, name = response_model, response_model.__name__
        self.calls.append(name)
        payloads = _payloads(messages)
        if name == 'IntroductionPages':
            return self._response(schema, self.selection, 'recorded_provider_response')
        if name == 'SummaryReadBatch':
            blocks = next(value for value in payloads if isinstance(value, list)
                          and value and 'block_id' in value[0])
            key = tuple(block['block_id'] for block in blocks)
            audit = next(record for record in self.intro['read_audits'] if tuple(record['block_ids']) == key)
            position = self.read_positions.get(key, 0)
            self.read_positions[key] = position + 1
            attempt = audit['attempts'][position]
            if 'response' not in attempt:
                self.provenance.append(dict(operation=name, provenance='recorded_schema_failure'))
                raise LLMStructuredOutputError('Recorded reading response failed its schema',
                    response=LLMResponse(text=attempt['raw_response'], usage=LLMUsage(
                        provider='mock', model='offline-recorded-artifact', finish_reason='stop')))
            return self._response(schema, attempt['response'], 'recorded_provider_response')
        if name == 'IntroductionAudienceSelection':
            # The failing historical response was NOT exported. This is a
            # labelled missing-ID protocol fault, not its reconstructed content.
            self.synthetic_decisions = _decisions(payloads[0]['parts'])
            return self._response(schema, dict(decisions=self.synthetic_decisions[:-1]),
                                  'synthetic_missing_id_protocol_fault')
        if name == 'IntroductionAudienceInventoryCorrection':
            return self._response(schema, dict(decisions=self.synthetic_decisions),
                                  'synthetic_inventory_protocol_correction')
        if name == 'IntroductionAudienceReview':
            self.review_inputs.append(deepcopy(payloads[-1]))
            self.provenance.append(dict(operation=name, provenance='unavailable_mandatory_review'))
            raise RecordedResponseUnavailable('Independent introduction review was not recorded')
        if name == 'InsightList':
            ids = {record['task_id'] for record in payloads[0]}
            insights = [item.model_dump(mode='json') for item in self.checkpoint.insights
                        if set(item.result_ids) <= ids]
            return self._response(schema, dict(insights=insights), 'saved_validated_artifact')
        if name == 'ReportPlan':
            return self._response(schema, self.checkpoint.report_plan.model_dump(mode='json'),
                                  'saved_validated_artifact')
        if name == 'PresentationTopicSelection':
            return self._response(schema, self.coverage['original_selection'], 'recorded_provider_response')
        if name == 'TopicCoverageReview':
            attempts = self.coverage['batches'][0]['attempts']
            if self.coverage_position >= len(attempts):
                raise RecordedResponseUnavailable('No further recorded topic coverage response')
            value = attempts[self.coverage_position]['review']
            self.coverage_position += 1
            return self._response(schema, value, 'recorded_provider_response')
        if name == 'VisualSelection':
            return self._response(schema, dict(suggestions=[]), 'synthetic_no_optional_visual_change')
        if name == 'BriefSourcePages':
            pages = list(dict.fromkeys(quote.page for item in self.checkpoint.executive_brief.items
                                       for quote in item.evidence))
            return self._response(schema, dict(pages=pages), 'synthetic_transport_from_saved_brief_pages')
        if name == 'ExecutiveBrief':
            return self._response(schema, self.checkpoint.executive_brief.model_dump(mode='json'),
                                  'saved_validated_artifact')
        if name == 'BriefMeaningReview':
            return self._meaning_response(payloads[0], schema)
        self.provenance.append(dict(operation=name, provenance='unavailable_newly_reachable_response'))
        raise RecordedResponseUnavailable('No historical response for ' + name)


class SyntheticReportingClient(SchemaReplayClient):
    """Independent source and review fixtures for full success/rejection wiring."""

    def __init__(self, source, *, accept_introduction):
        super().__init__()
        self.source = source
        self.accept_introduction = accept_introduction
        self.calls, self.decisions, self.author_calls = [], None, 0

    def generate_structured(self, messages, response_model, **kwargs):
        schema, name = response_model, response_model.__name__
        self.calls.append(name)
        values = _payloads(messages)
        if name == 'IntroductionPages':
            value = dict(pages=[2], summary_ranges=[dict(start_page=2, end_page=2,
                reason='The complete synthetic introductory source is on this page.')])
        elif name == 'SummaryReadBatch':
            parts = []
            for block in values[0]:
                for index, line in block['lines']:
                    content = line.strip() != 'SUMMARY'
                    parts.append(dict(block_id=block['block_id'], start_line=index, end_line=index,
                        title='Business and delivery' if content else 'Summary heading',
                        role='content' if content else 'heading', reading_note='The whole assigned line was read.',
                        facts=[dict(label='Business and delivery', text=line.strip(),
                                    quote_start_line=index, quote_end_line=index)] if content else []))
            value = dict(parts=parts)
        elif name == 'IntroductionAudienceSelection':
            self.author_calls += 1
            self.decisions = [dict(part_id=part['id'], include=True,
                reason='The business and its delivery prerequisite define the synthetic introduction.',
                required_meanings=[dict(meaning=part['source_text'].strip())]) for part in values[0]['parts']]
            value = dict(decisions=self.decisions[:-1] if self.author_calls == 1 else self.decisions)
        elif name == 'IntroductionAudienceInventoryCorrection':
            value = dict(decisions=self.decisions)
        elif name == 'IntroductionAudienceReview':
            from tests.introduction_review_helpers import review_response
            value = review_response(schema, messages, accepted=self.accept_introduction, repair_scope='selection',
                reason='The synthetic business and prerequisite are supported.' if self.accept_introduction
                else 'The independent fixture rejects this proposed source selection.').model_dump(mode='json')
        elif name == 'SummarySynthesisDraft':
            parts = values[0]['parts']
            text = ' '.join(part['required_meanings'][0]['meaning'] for part in parts)
            value = dict(pages=[dict(title='Software and delivery', items=[dict(label='Business and delivery',
                text=text, meaning_refs=_synthetic_meaning_refs(parts, text),
                fact_ids=[fact['id'] for part in parts for fact in part['facts']])])])
        elif name == 'SummaryCoverageReview':
            payload = values[-1]
            value = dict(parts=[dict(part_id=part['id'], accepted=True,
                reason='The entire synthetic source assertion is visible.',
                coverage=[dict(meaning_index=index, covered=True, summary_quote=meaning['meaning'],
                    reason='This exact source assertion is bound to the visible paragraph.')
                    for index, meaning in enumerate(part['required_meanings'])]) for part in payload['source']['parts']],
                opening_accepted=True, opening_reason='The opening explains the scheduling software business.',
                opening_slide_id=payload['opening_target']['slide_id'],
                opening_item_texts=payload['opening_target']['item_texts'], identity_accepted=None)
        elif name == 'PresentationTopicSelection':
            value = self.source.presentation_topics.model_dump(mode='json')
        elif name == 'VisualSelection':
            value = dict(suggestions=[])
        elif name == 'ExecutiveBrief':
            value = dict(title='Key takeaways', items=[dict(label=f'Subject {letter}',
                text=self.source.document.pages[position].text,
                evidence=[dict(page=self.source.document.pages[position].page_number,
                               text=self.source.document.pages[position].text)])
                for letter, position in [('A', 0), ('B', 2)]])
        elif name == 'BriefMeaningReview':
            value = dict(items=[dict(index=row['index'], accepted=True,
                reason='Exact separately dated synthetic source facts are retained.',
                numeric_comparison=False, comparisons=[]) for row in values[0]])
        elif name == 'BriefClaimDirectionReview':
            assert all(not row['comparisons'] for row in values[0])
            value = dict(items=[dict(index=row['index'], comparisons=[],
                omitted_directional_claims=[]) for row in values[0]])
        else:
            raise AssertionError('Unexpected synthetic reporting operation: ' + name)
        from tests.summary_author_helpers import writer_test_value
        typed = schema.model_validate(writer_test_value(schema, value))
        return typed, LLMResponse(text=typed.model_dump_json(), usage=LLMUsage(provider='mock', model='synthetic'))


def _synthetic_checkpoint():
    from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget, fixed_presentation_budget
    from tests.test_topic_summary_coverage import _topic_result
    source = _topic_result(count=2, copies=1)
    raw = b'synthetic-reporting-checkpoint-pdf-boundary'
    source.document.sha256 = hashlib.sha256(raw).hexdigest()
    source.document.page_count = 12
    source.document.pages = [DocumentPage(page_number=page, text=(
        f'Subject {letter} was 10 units in FY2023, 11 units in FY2024 and 12 units in FY2025.'))
        for page, letter in [(1, 'A'), (11, 'B')]]
    source.document.pages.insert(1, DocumentPage(page_number=2, text=(
        'SUMMARY\nWe provide scheduling software for operating teams.\n'
        'Staff training is required before service delivery.\n')))
    by_page = {page.page_number: page for page in source.document.pages}
    for item in source.observations:
        item.evidence[0].text = by_page[item.evidence[0].page].text
    source.profile.analysis_page_ranges = [(1, 12)]
    source.profile.document_summary_pages = [2]
    source.profile.report_requirements = apply_presentation_budget(None, '', fixed_presentation_budget())
    source.presentation_plan = None
    source.pipeline_version = PIPELINE_VERSION
    source.pipeline_state, source.retry_from = 'partial', 'reporting'
    return source, raw


@pytest.mark.parametrize('accepted', [True, False])
def test_full_reporting_retry_keeps_inventory_and_independent_export_gates(monkeypatch, accepted):
    source, raw = _synthetic_checkpoint()
    original = source.model_copy(deep=True)
    client = SyntheticReportingClient(source, accept_introduction=accepted)
    runner = DocumentOrchestrator(_gateway(client))
    monkeypatch.setattr(runner, '_load_document', lambda data, digest:
        source.document if data == raw and digest == source.document.sha256 else pytest.fail('Wrong source bytes'))
    result = runner.analyse_pdf(raw, resume=source)
    assert source == original
    assert result.observations == source.observations
    assert 'IntroductionAudienceInventoryCorrection' in client.calls
    assert 'IntroductionAudienceReview' in client.calls
    assert not any(issue.code == 'presentation_plan_fallback' for issue in result.validation_warnings)
    from adaptive_document_agent.services.company_summary import require_verified_introduction
    from adaptive_document_agent.services.pptx_export import build_presentation
    if accepted:
        assert result.executive_brief is not None
        assert result.presentation_plan.planning_origin == 'topic_compilation'
        assert is_complete(result)
        require_verified_introduction(result)
        assert 'SummaryCoverageReview' in client.calls
        data = build_presentation(result)
        assert data.startswith(b'PK')
    else:
        assert not is_complete(result) and result.pipeline_state == 'partial'
        assert result.executive_brief is None
        assert not any(name in client.calls for name in ('BriefSourcePages', 'ExecutiveBrief', 'BriefMeaningReview'))
        assert 'SummarySynthesisDraft' not in client.calls
        with pytest.raises(ValueError, match='source-verified opening introduction'):
            build_presentation(result)


@pytest.mark.skipif(not os.environ.get('ADA_REPORT_CHECKPOINT'), reason='External retained reporting checkpoint not configured')
def test_external_v141_checkpoint_whole_reporting_retry_retains_unavailable_review_boundary():
    checkpoint_path = Path(os.environ['ADA_REPORT_CHECKPOINT'])
    pdf_path = Path(os.environ['ADA_REPORT_SOURCE_PDF'])
    original_bytes, raw = checkpoint_path.read_bytes(), pdf_path.read_bytes()
    before_hash = hashlib.sha256(original_bytes).hexdigest()
    checkpoint = PipelineResult.model_validate_json(original_bytes)
    assert checkpoint.pipeline_version == SUPPORTED_RECORDED_VERSION
    assert checkpoint.pipeline_state == 'partial' and checkpoint.retry_from == 'reporting'
    assert hashlib.sha256(raw).hexdigest() == checkpoint.document.sha256
    original = checkpoint.model_copy(deep=True)
    retry = checkpoint.model_copy(deep=True)
    # Only the test fixture adopts the unchanged v19 extraction/v74 analysis
    # contract. The production version/hash/state guards run without patches.
    retry.pipeline_version = PIPELINE_VERSION
    client = CheckpointClient(checkpoint)
    result = DocumentOrchestrator(_gateway(client)).analyse_pdf(raw, resume=retry)
    assert checkpoint == original
    assert hashlib.sha256(checkpoint_path.read_bytes()).hexdigest() == before_hash
    assert result.observations == original.observations
    assert result.analysis_results == original.analysis_results
    assert result.executive_brief is None
    if result.presentation_plan is not None:
        assert result.presentation_plan.planning_origin == 'topic_compilation'
        assert len(result.presentation_plan.themes) == len(original.presentation_topics.topics)
    assert not any(issue.code == 'presentation_plan_fallback' for issue in result.validation_warnings)
    assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    assert client.review_inputs
    review = client.review_inputs[0]
    assert len(review['source']['parts']) == len(review['decisions'])
    assert len(review['inventory_revision_base']['decisions']) == len(review['decisions']) - 1
    kinds = {row['provenance'] for row in client.provenance}
    assert {'recorded_provider_response', 'saved_validated_artifact',
            'synthetic_missing_id_protocol_fault', 'synthetic_inventory_protocol_correction',
            'unavailable_mandatory_review'} <= kinds
    assert not any(name in client.calls for name in ('BriefSourcePages', 'ExecutiveBrief', 'BriefMeaningReview'))
    assert 'SummarySynthesisDraft' not in client.calls
    from adaptive_document_agent.services.pptx_export import build_presentation
    with pytest.raises(ValueError, match='source-verified opening introduction'):
        build_presentation(result)
