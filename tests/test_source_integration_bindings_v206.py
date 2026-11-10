"""Three originals plus two additions have five reviewable, exact addresses."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_integration_review import (
    SourceIntegrationDraft, review_supplementary_sources, resolved_source_check_ids,
)
from adaptive_document_agent.models.coverage import SourceCheck
from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from tests.test_source_integration_v166 import fixture
from tests.test_executive_brief import payload


def case():
    result, constraint = fixture()
    for label, text in [('Operations', 'Operations continued.'), ('Demand', 'Demand remained uncertain.')]:
        result.document.pages[0].text += '\n' + text
        result.executive_brief.items.append(ExecutiveBriefItem.model_validate(payload(text, 1, label)['items'][0]))
    other = 'The forecast depends on continued customer renewals.'
    result.document.pages[11].text += '\n' + other
    result.profile.source_coverage.checks.append(SourceCheck(section_id='outlook', pages=[12],
        reason='Read forecast conditions.', decision_impact='Qualifies expected demand.',
        status='checked_found', finding=other, evidence_quotes={12: [other]}))
    draft = SourceIntegrationDraft(additions=[
        payload(constraint, 12, 'Cancellation')['items'][0],
        payload(other, 12, 'Forecast conditions')['items'][0]], decisions=[
            dict(section_id=sid, disposition='include', reason='Material source qualification.',
                 evidence=[dict(page=12, text=text)], brief_item_indexes=[index])
            for sid, text, index in [('contracts', constraint, 3), ('outlook', other, 4)]])
    return result, draft


@pytest.mark.parametrize('interrupt', [False, True])
def test_full_brief_repairs_rejected_additions_in_place_and_resumes_after_timeout(interrupt):
    from adaptive_document_agent.services.analysis_deadline import AnalysisTimeLimitExceeded

    result, draft = case()
    original_text = 'Production continued during the reporting period.'
    result.document.pages[0].text += '\n' + original_text
    result.executive_brief.items.append(ExecutiveBriefItem.model_validate(payload(original_text, 1, 'Production')['items'][0]))
    supplement = 'Cancellation also requires written notice.'
    result.document.pages[11].text += '\n' + supplement
    draft.additions.append(ExecutiveBriefItem.model_validate(payload(supplement, 12, 'Notice')['items'][0]))
    draft.decisions[0].brief_item_indexes = [4, 6]
    draft.decisions[1].brief_item_indexes = [5]
    calls = []
    retrying = False

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            if schema is SourceIntegrationDraft:
                assert len(calls) == 1
                context = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                assert context['maximum_additions'] == 3
                return draft.model_copy(deep=True)
            if schema.__name__ == 'ReopenedSourceAdditions':
                assert set(schema.model_fields) == {'item_4', 'item_6'}
                if interrupt and not retrying:
                    raise AnalysisTimeLimitExceeded()
                return schema(item_4=draft.additions[0].model_copy(update={'label': 'Cancellation scope'}),
                              item_6=draft.additions[2])
            return schema(verdicts=[dict(section_id=d.section_id, accepted=i == 1 or len(calls) >= 4,
                reason='Independent source review.') for i, d in enumerate(draft.decisions)])

    original = result.executive_brief
    if interrupt:
        with pytest.raises(AnalysisTimeLimitExceeded):
            review_supplementary_sources(Gateway(), result, original)
        assert result.validation_warnings[-1].code == 'source_integration_unresolved'
        assert not resolved_source_check_ids(result, original)
        result.pipeline_state, result.retry_from, result.failed_stage = 'partial', 'reporting', 'analysis_time_limit'
        result.failure_details = dict(component='AnalysisTimeLimit')
        previous = result.model_copy(deep=True)
        retrying = True
    else:
        previous = None
    merged = review_supplementary_sources(Gateway(), result, original, previous=previous)
    assert calls == ['SourceIntegrationDraft', 'SourceIntegrationReview', 'ReopenedSourceAdditions',
                     *(['ReopenedSourceAdditions'] if interrupt else []), 'SourceIntegrationReview']
    assert len(merged.items) == 7 and merged.items[:4] == original.items
    assert merged.items[5] == draft.additions[1]
    assert merged.items[4].label == 'Cancellation scope'
    assert resolved_source_check_ids(result, merged) == {'contracts', 'outlook'}


@pytest.mark.parametrize('accept_fresh', [False, True])
@pytest.mark.parametrize('numeric_correction', [False, True])
def test_retry_edits_only_rejected_addition_but_rechecks_every_section(accept_fresh, numeric_correction):
    from adaptive_document_agent.models import ValidationIssue
    result, draft = case()
    result.failed_stage = 'source_integration'
    result.validation_warnings.append(ValidationIssue(code='source_integration_unresolved',
        stage='report', message=json.dumps(dict(attempts=[dict(draft=draft.model_dump(mode='json'),
        review=dict(verdicts=[dict(section_id=d.section_id, accepted=i == 1,
            reason='Scope needs a correction.' if i == 0 else 'Supported.')
            for i, d in enumerate(draft.decisions)]))]))))
    previous = result.model_copy(deep=True)
    calls = []
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            if schema.__name__ == 'ReopenedSourceAdditions':
                assert set(schema.model_fields) == ({'item_3'} if 'SourceIntegrationReview' not in calls else {'item_3', 'item_4'})
                values = {key: draft.additions[int(key[5:]) - 3].model_copy(
                    update={'label': 'Source scope'}) for key in schema.model_fields}
                if numeric_correction and len(calls) == 1:
                    values['item_3'].text += ' Invented value 987654321.'
                return schema(**values)
            if schema is SourceIntegrationDraft:
                return draft
            return schema(verdicts=[dict(section_id=d.section_id, accepted=accept_fresh,
                reason='Fresh complete source review.') for d in draft.decisions])
    merged = review_supplementary_sources(Gateway(), result, result.executive_brief, previous=previous)
    assert calls[:2 + numeric_correction] == ['ReopenedSourceAdditions'] * (1 + numeric_correction) + ['SourceIntegrationReview']
    assert 'SourceIntegrationDraft' not in calls
    assert bool(resolved_source_check_ids(result, merged)) is accept_fresh
    assert merged.items[:3] == previous.executive_brief.items
    if accept_fresh:
        assert merged.items[4] == draft.additions[1]
    else:
        assert merged == previous.executive_brief


@pytest.mark.parametrize('outcome', ['accepted', 'overlong', 'forged'])
def test_overlong_targeted_retry_preserves_locks_and_recovers_its_checkpoint(outcome):
    from adaptive_document_agent.models import ValidationIssue
    from adaptive_document_agent.agent.source_integration_review import _retry_draft
    from adaptive_document_agent.agent.source_integration_resume import rejected_addition_sections
    from tests.test_budget_output_v145 import gateway, response
    result, draft = case()
    result.failed_stage = 'source_integration'
    verdicts = [dict(section_id=d.section_id, accepted=i == 1, reason='Prior source review.')
                for i, d in enumerate(draft.decisions)]
    result.validation_warnings.append(ValidationIssue(code='source_integration_unresolved', stage='report',
        message=json.dumps(dict(attempts=[dict(draft=draft.model_dump(mode='json'), review=dict(verdicts=verdicts))]))))
    previous = result.model_copy(deep=True)
    invalid = draft.additions[0].model_dump(mode='json')
    invalid['text'] *= 20
    assert len(invalid['text']) > 550
    body = (invalid['text'] if outcome == 'overlong' else draft.additions[0].text
            + (' Invented value 987654321.' if outcome == 'forged' else ''))
    outputs = [response(json.dumps(dict(item_3=invalid))), response(json.dumps(dict(
        addition_0_text=[dict(label=draft.additions[0].label, text=body)])))]
    if outcome == 'accepted':
        outputs.append(response(json.dumps(dict(verdicts=[{**v, 'accepted': True} for v in verdicts]))))
    llm, _ = gateway(outputs)
    merged = review_supplementary_sources(llm, result, result.executive_brief, previous=previous)
    operations = [u['operation'] for u in llm.usage]
    assert operations == ['ReopenedSourceAdditions', 'SourceAdditionCopy',
                          *(['SourceIntegrationReview'] if outcome == 'accepted' else [])]
    if outcome == 'accepted':
        assert merged.items[4] == draft.additions[1]
        assert resolved_source_check_ids(result, merged) == {'contracts', 'outlook'}
    else:
        assert merged == previous.executive_brief
        assert not resolved_source_check_ids(result, merged)
        checks = result.profile.source_coverage.checks_by_review_id()
        pages = {p.page_number: p.text for p in result.document.pages}
        retained = _retry_draft(result, result, merged, checks, pages)
        assert retained == draft
        assert rejected_addition_sections(result, retained, checks, len(merged.items))[1] == ['contracts']


@pytest.mark.parametrize('accepted', [True, False])
def test_reviewer_sees_exact_addition_at_index_four_and_still_owns_semantic_verdict(accepted):
    result, draft = case()
    original = result.executive_brief.model_copy(deep=True)
    sources = deepcopy(result.document)
    class Gateway:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if schema is SourceIntegrationDraft:
                return draft.model_copy(deep=True)
            context = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert context['original_brief_item_count'] == 3
            assert context['original_brief'] == original.model_dump(mode='json')
            ledger = context['merged_brief_items']
            assert [row['index'] for row in ledger] == list(range(5))
            assert [row['origin'] for row in ledger] == ['original'] * 3 + ['addition'] * 2
            assert ledger[4]['item'] == draft.additions[1].model_dump(mode='json')
            assert context['resolved_source_bindings'][1]['items'] == [dict(index=4, origin='addition')]
            assert context['source_pages'][0]['text'] == result.document.pages[11].text
            return schema(verdicts=[dict(section_id=d.section_id, accepted=accepted,
                reason='Exact added item carries the source condition.' if accepted else
                       'The bound finding misses a material condition.') for d in draft.decisions])
    gateway = Gateway()
    result.executive_brief = review_supplementary_sources(gateway, result, original)
    assert result.document == sources
    assert result.executive_brief.items[:3] == original.items
    if accepted:
        assert len(result.executive_brief.items) == 5
        assert resolved_source_check_ids(result, result.executive_brief) == {'contracts', 'outlook'}
        assert gateway.calls == 2
    else:
        assert result.executive_brief == original
        assert not resolved_source_check_ids(result, original)
        assert gateway.calls == 4


@pytest.mark.parametrize('mutation', ['out_of_range', 'covered_addition', 'include_original'])
def test_invalid_addresses_never_reach_the_independent_reviewer(mutation):
    result, draft = case()
    if mutation == 'out_of_range':
        draft.decisions[1].brief_item_indexes = [5]
    elif mutation == 'covered_addition':
        draft.decisions[1].disposition = 'covered'
    else:
        draft.decisions[1].brief_item_indexes = [0]
    class Gateway:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert schema is SourceIntegrationDraft
            return draft
    gateway = Gateway()
    original = result.executive_brief.model_copy(deep=True)
    assert review_supplementary_sources(gateway, result, original) == original
    assert gateway.calls == 2
    assert not resolved_source_check_ids(result, original)


@pytest.mark.parametrize('shared', [False, True])
def test_revised_draft_keeps_only_separately_accepted_additions(shared):
    result, draft = case()
    revision = draft.model_copy(deep=True)
    revision.additions[0].text += ' Unsupported figure 9999.'
    revision.decisions[0].disposition = 'covered'
    revision.decisions[0].brief_item_indexes.insert(0, 0)
    if shared:
        revision.decisions[1].brief_item_indexes.append(3)
    class Gateway:
        drafts = 0
        reviews = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema is SourceIntegrationDraft:
                self.drafts += 1
                return draft if self.drafts == 1 else revision
            self.reviews += 1
            return schema(verdicts=[dict(section_id=d.section_id,
                accepted=(self.reviews == 2 or d.section_id == 'contracts'),
                reason='Independently assessed source support.') for d in draft.decisions])
    gateway = Gateway()
    original = result.executive_brief
    merged = review_supplementary_sources(gateway, result, original)
    audit = json.loads(result.validation_warnings[-1].message)
    last = audit['attempts'][-1]
    if shared:
        assert merged == original and gateway.reviews == 1 and last['preserved_sections'] == []
    else:
        assert merged.items[3] == draft.additions[0] and gateway.reviews == 2
        assert last['preserved_sections'] == ['contracts']
        assert last['submitted_draft']['additions'][0]['text'] == revision.additions[0].text


@pytest.mark.parametrize('mixed_rejection', [False, True])
@pytest.mark.parametrize('accept_final', [False, True])
def test_reopened_unchanged_section_gets_its_first_correction_after_companion_changes(mixed_rejection, accept_final):
    result, draft = case()
    class Gateway:
        drafts = reviews = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'ReopenedSourceAdditions':
                assert set(schema.model_fields) == ({'item_3', 'item_4'} if mixed_rejection else {'item_3'})
                packet = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                assert set(packet['items_to_revise']) == set(schema.model_fields)
                assert packet['items_to_revise']['item_3']['current_item']['text'] == draft.additions[0].text
                assert packet['items_to_revise']['item_3']['section_ids'] == ['contracts']
                values = dict(item_3=draft.additions[0].model_copy(update={'label': 'Cancellation scope'}))
                if mixed_rejection:
                    values['item_4'] = draft.additions[1].model_copy(update={'label': 'Forecast scope'})
                return schema(**values)
            if schema is SourceIntegrationDraft:
                self.drafts += 1
                value = draft.model_copy(deep=True)
                if self.drafts >= 2:
                    value.additions[1].label = 'Forecast scope'
                return value
            self.reviews += 1
            return schema(verdicts=[dict(section_id=d.section_id,
                accepted=((self.reviews == 3 and accept_final)
                          or self.reviews < 3 and i == self.reviews - 1
                          and not (mixed_rejection and self.reviews == 2)),
                reason='Scope independently reviewed.')
                for i, d in enumerate(draft.decisions)])
    gateway = Gateway()
    merged = review_supplementary_sources(gateway, result, result.executive_brief)
    assert gateway.reviews == 3
    assert resolved_source_check_ids(result, merged) == ({'contracts', 'outlook'} if accept_final else set())
    if accept_final:
        assert [item.label for item in merged.items[-2:]] == ['Cancellation scope', 'Forecast scope']
    else:
        assert merged == result.executive_brief
