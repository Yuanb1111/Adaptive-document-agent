"""Local revisions preserve unaddressed qualifications and exact source bindings."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.retained_page_revision import (
    RetainedCopyEdit, apply_copy_edits, revise_retained_pages, copy_span_catalog,
)
from adaptive_document_agent.agent.retained_page_sources import source_row_assurance, writer_context
from adaptive_document_agent.agent.retained_selection_feedback import (
    restore_rejected_findings, retain_selection_feedback, selection_retry_feedback,
)
from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.models import PipelineResult
from tests.test_retained_analysis_v216 import gateway
from tests.test_retained_source_citations import fixture


def test_disjoint_edits_use_the_original_offsets_and_preserve_other_qualifications():
    original = 'The buffer was reported. The adverse aging qualification remains. Management monitors the balance.'
    edits = [RetainedCopyEdit(before='The buffer was reported.', after='The buffer is reported for FY2023.'),
             RetainedCopyEdit(before='Management monitors the balance.', after='Management monitors the reported balance.')]
    final = apply_copy_edits(original, edits)
    assert final == ('The buffer is reported for FY2023. The adverse aging qualification remains. '
                     'Management monitors the reported balance.')
    assert apply_copy_edits(original, list(reversed(edits))) == final


@pytest.mark.parametrize('before', ['Missing passage.', 'Repeated.'])
def test_edit_requires_one_literal_original_occurrence(before):
    with pytest.raises(ValueError, match='exactly one original span'):
        apply_copy_edits('Repeated. Repeated.', [RetainedCopyEdit(before=before, after='Rewritten.')])


def test_overlapping_edits_cannot_apply_sequentially_or_erase_context():
    with pytest.raises(ValueError, match='must not overlap'):
        apply_copy_edits('The adverse source qualification.', [
            RetainedCopyEdit(before='adverse source', after='revised'),
            RetainedCopyEdit(before='source qualification', after='replacement')])


def test_overlapping_occurrences_are_still_ambiguous():
    with pytest.raises(ValueError, match='exactly one original span'):
        apply_copy_edits('aaa', [RetainedCopyEdit(before='aa', after='b')])


def test_span_ids_replace_the_selected_occurrence_without_transcribing_source_copy():
    text = 'Repeated sentence. Repeated sentence. A final qualification remains.'
    catalog = copy_span_catalog(text)
    assert [p['text'] for p in catalog] == ['Repeated sentence.', 'Repeated sentence.',
                                           'A final qualification remains.']
    assert apply_copy_edits(text, [RetainedCopyEdit(span_id='copy-1', after='Corrected sentence.')]) == (
        'Repeated sentence. Corrected sentence. A final qualification remains.')
    with pytest.raises(ValueError, match='Unknown copy span ID'):
        apply_copy_edits(text, [RetainedCopyEdit(span_id='copy-99', after='Wrong.')])
    with pytest.raises(ValueError, match='must not overlap'):
        apply_copy_edits(text, [RetainedCopyEdit(span_id='copy-2', after='New.'),
            RetainedCopyEdit(before='final qualification', after='other context')])


@pytest.mark.parametrize('locators', [{}, dict(before='Source.', span_id='copy-0')])
def test_span_edit_requires_exactly_one_locator(locators):
    with pytest.raises(ValueError, match='Choose exactly one'):
        RetainedCopyEdit(after='Replacement.', **locators)


@pytest.mark.parametrize('changed_source', [False, True])
def test_intro_failure_reuses_only_the_source_matched_completed_selection(changed_source):
    previous, _, selection = fixture()
    retained.select_retained_analysis(gateway([selection.model_dump(), dict(
        accepted=True, reason='Synthetic source selection.')]), previous)
    previous.presentation_plan = retained.compile_retained_analysis(previous)
    previous.failed_stage = 'introduction_reading'
    previous.failure_details = dict(operation='SummaryReadBatch', kind='format')
    current = PipelineResult(document=deepcopy(previous.document), profile=deepcopy(previous.profile),
        observations=deepcopy(previous.observations), analysis_plan=deepcopy(previous.analysis_plan),
        analysis_results=deepcopy(previous.analysis_results))
    if changed_source:
        current.document.pages[0].text += ' Changed source.'
    assert restore_rejected_findings(previous, current) is not changed_source
    if not changed_source:
        assert retained.selected_record(current) == retained.selected_record(previous)
        assert current.insights == previous.insights
    assert current.presentation_plan is None
    assert not any(w.code == 'presentation_retained_analysis_review' for w in current.validation_warnings)


@pytest.mark.parametrize('changed_source', [False, True])
def test_final_source_rejection_keeps_findings_and_eligibility_without_approval(changed_source):
    from adaptive_document_agent.agent.retained_analysis_review import review_retained_analysis, review_complete
    previous, _, selection = fixture()
    retained.select_retained_analysis(gateway([selection.model_dump(), dict(
        accepted=True, reason='Synthetic source selection.')]), previous)
    previous.presentation_plan = retained.compile_retained_analysis(previous)
    slides = [s for s in previous.presentation_plan.slides if s.slide_type == 'analysis']
    mock = gateway([dict(verdicts=[dict(slide_id=s.id, accepted=False,
        reason='Preserve the qualitative source qualification.') for s in slides],
        omissions_accepted=True, omission_reason='Synthetic material selection.')])
    with pytest.raises(ValueError, match='evidence review rejected'):
        review_retained_analysis(mock, previous)
    assert 'planned_source_citations' in json.dumps(mock.client.calls)
    previous.failed_stage = 'presentation_coverage'
    previous.failure_details = dict(component='PresentationCoverage')
    current = PipelineResult(document=previous.document.model_copy(deep=True),
        profile=previous.profile.model_copy(deep=True),
        observations=deepcopy(previous.observations), analysis_plan=deepcopy(previous.analysis_plan),
        analysis_results=deepcopy(previous.analysis_results))
    feedback = retain_selection_feedback(previous)
    assert feedback and json.loads(feedback.message)['source_review'] is True
    current.validation_warnings.append(feedback)
    if changed_source:
        current.document.pages[0].text += ' Changed original evidence.'
    assert restore_rejected_findings(previous, current) is not changed_source
    if not changed_source:
        assert current.insights == previous.insights
        assert selection_retry_feedback(current, retained.selection_context(current, source_authoring=True))
    assert not review_complete(previous)
    assert retained.selected_record(current) is None
    assert not any(w.code == 'presentation_retained_analysis_review' for w in current.validation_warnings)
    if not changed_source:
        iid = selection.ordered_insight_ids[0]
        original = selection.decisions[0].page.message
        local = gateway([dict(edits={iid: dict(message=[dict(before=original,
            after='The source reports revenue with its period labels.')])}),
            dict(accepted=True, reason='Synthetic independent corrected-copy review.')])
        retained.select_retained_analysis(local, current)
        assert [row['operation'] for row in local.usage] == [
            'RetainedPageRevisions', 'RetainedSelectionCoverage']
        assert 'earlier_review_questions' in str(local.client.calls[1])
        assert 'Preserve the qualitative source qualification.' in str(local.client.calls[1])
        assert retained.selected_record(current)['selection']['ordered_insight_ids'] == [iid]
        assert not review_complete(current)


@pytest.mark.parametrize('problem', [None, 'unflagged', 'duplicate_mode', 'invalid_span'])
def test_production_revision_merges_only_the_addressed_spans(problem):
    result, context, selection = fixture()
    iid = selection.ordered_insight_ids[0]
    before = deepcopy((result, selection))
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    original = selection.decisions[0].page
    response = {'edits': {iid: dict(message=[dict(before=original.message,
        after='The source reports the revenue balance.')])}}
    if problem == 'unflagged':
        response['edits']['unflagged'] = response['edits'].pop(iid)
    elif problem == 'duplicate_mode':
        response['pages'] = {iid: original.model_dump()}
    elif problem == 'invalid_span':
        response['edits'][iid]['message'][0]['before'] = 'Invented prior copy.'
    mock = gateway([response, response] if problem == 'invalid_span' else [response])
    def run():
        return revise_retained_pages(mock, result, packet, aliases, selection.model_dump(),
            {iid: ['Clarify the reported balance.']}, earlier_issues={iid: ['Preserve the source qualification.']})
    if problem:
        with pytest.raises(ValueError):
            run()
    else:
        revised = run()[iid]
        assert revised.message == 'The source reports the revenue balance.'
        assert revised.model_dump(exclude={'message'}) == original.model_dump(exclude={'message'})
        assert 'Preserve the source qualification.' in json.dumps(mock.client.calls)
    assert (result, selection) == before


@pytest.mark.parametrize('failure', ['missing_span', 'merged_length'])
def test_span_and_merged_length_failures_get_one_contract_correction(failure):
    result, context, selection = fixture()
    iid = selection.ordered_insight_ids[0]
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    original = selection.decisions[0].page.message
    broken = (dict(before='Missing draft sentence.', after='Reported revenue.')
              if failure == 'missing_span' else dict(before='reports', after='x' * 1990))
    mock = gateway([dict(edits={iid: dict(message=[broken])}),
                    dict(edits={iid: dict(message=[dict(before=original, after='Reported revenue.')])})])
    revised = revise_retained_pages(mock, result, packet, aliases, selection.model_dump(),
                                   {iid: ['Clarify source attribution.']})
    assert revised[iid].message == 'Reported revenue.'
    assert len(mock.client.calls) == 2
    assert selection.decisions[0].page.message == original


def test_local_numeric_input_freeze_uses_the_shared_bounded_contract_correction(monkeypatch):
    from adaptive_document_agent.agent import retained_page_revision
    result, context, selection = fixture()
    iid = selection.ordered_insight_ids[0]
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    monkeypatch.setattr(retained_page_revision, 'copy_contract_errors', lambda *_: {})
    selection.decisions[0].page.companion_ids = ['kept-row']
    mock = gateway([dict(edits={iid: dict(companion_ids=[])}),
                    dict(edits={iid: dict(companion_ids=['kept-row'])})])
    revised = revise_retained_pages(mock, result, packet, aliases, selection.model_dump(),
        {iid: ['Correct only source attribution.']}, preserve_numeric_inputs=True)
    assert revised[iid].companion_ids == ['kept-row']
    assert len(mock.client.calls) == 2
    assert 'Existing numeric inputs are frozen' in str(mock.client.calls[1])
    assert selection.decisions[0].page.companion_ids == ['kept-row']


def test_recorded_retry_keeps_all_current_source_questions_without_approving_them():
    path = os.getenv('ADA_RETAINED_COPY_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_RETAINED_COPY_DIAGNOSTIC to the private retained-copy checkpoint.')
    result = PipelineResult.model_validate_json(Path(path).read_bytes())
    original = result.model_dump_json()
    feedback = retain_selection_feedback(result)
    record = json.loads(feedback.message)
    questions = record['earlier_page_issues']
    for warning in result.validation_warnings:
        if warning.code == 'retained_selection_coverage':
            review = json.loads(warning.message)['review']
            for issue in review['page_issues']:
                if issue['insight_id'] in questions:
                    assert issue['reason'] in questions[issue['insight_id']]
    assert any(len(reasons) > 2 for reasons in questions.values())
    assert result.model_dump_json() == original
    result.validation_warnings.append(feedback)
    current = selection_retry_feedback(result, retained.selection_context(result, source_authoring=True))
    assert current['earlier_page_issues'] == questions
    assert current['final_approval'] is False


def test_edit_contract_retry_freezes_valid_siblings_and_rechecks_new_amounts():
    result, context, selection = fixture()
    iid = selection.ordered_insight_ids[0]
    other = 'other-retained-finding'
    result.insights.append(result.insights[0].model_copy(update={'id': other}))
    context = retained.selection_context(result, source_authoring=True)
    sibling = selection.decisions[0].model_copy(deep=True, update={'insight_id': other})
    selection.decisions.append(sibling)
    selection.ordered_insight_ids.append(other)
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    original = selection.decisions[0].page.message
    invalid = 'The revenue balance was RMB999,999,999 thousand.'
    mock = gateway([dict(edits={iid: dict(message=[dict(before=original, after=invalid)]),
                               other: dict(message=[dict(before=original, after='The source also reports revenue.')])}),
                    dict(edits={iid: dict(message=[dict(before=invalid, after=original)])})])
    revised = revise_retained_pages(mock, result, packet, aliases, selection.model_dump(),
                                   {iid: ['Clarify the reported balance.'], other: ['Clarify the attribution.']})
    assert revised[iid].message == original
    assert revised[other].message == 'The source also reports revenue.'
    assert len(mock.client.calls) == 2
    assert 'outside its bound evidence' in json.dumps(mock.client.calls[1])
    from adaptive_document_agent.utils.record_encoding import decode_records
    wire = mock.client.calls[1][-1]['content']
    payload = decode_records(json.loads(wire.split('\n', 1)[1].rsplit('\n', 1)[0]))
    assert set(payload['pages_to_correct']) == {iid}
    assert selection.decisions[0].page.message == original


def test_second_invalid_edit_contract_cannot_request_another_retry():
    result, context, selection = fixture()
    iid = selection.ordered_insight_ids[0]
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    original = selection.decisions[0].page.message
    invalid = 'The revenue balance was RMB999,999,999 thousand.'
    mock = gateway([dict(edits={iid: dict(message=[dict(before=original, after=invalid)])}),
                    dict(edits={iid: dict(message=[])})])
    with pytest.raises(ValueError, match='outside its bound evidence'):
        revise_retained_pages(mock, result, packet, aliases, selection.model_dump(),
                              {iid: ['Clarify the reported balance.']})
    assert len(mock.client.calls) == 2


@pytest.mark.parametrize('mutation', [None, 'source', 'calculation', 'missing_feedback'])
def test_recorded_selection_retry_reuses_findings_only_for_identical_inputs(mutation):
    path = os.getenv('ADA_RETAINED_COPY_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_RETAINED_COPY_DIAGNOSTIC to the private retained-copy checkpoint.')
    previous = PipelineResult.model_validate_json(Path(path).read_bytes())
    current = PipelineResult(document=previous.document.model_copy(deep=True),
        profile=previous.profile.model_copy(deep=True),
        observations=[o.model_copy(deep=True) for o in previous.observations],
        analysis_plan=[t.model_copy(deep=True) for t in previous.analysis_plan],
        analysis_results=[r.model_copy(deep=True) for r in previous.analysis_results])
    if mutation != 'missing_feedback':
        current.validation_warnings.append(retain_selection_feedback(previous))
    if mutation == 'source':
        current.document.pages[0].text += 'Changed source.'
    elif mutation == 'calculation':
        current.analysis_results[0].confidence = .123
    original = previous.model_dump_json()
    assert restore_rejected_findings(previous, current) is (mutation is None)
    if mutation is None:
        assert current.insights == previous.insights and current.report_plan == previous.report_plan
        assert current.insights is not previous.insights
        assert selection_retry_feedback(current, retained.selection_context(current, source_authoring=True))
    else:
        assert not current.insights
    assert previous.model_dump_json() == original


@pytest.mark.parametrize('mutation', [None, 'incomplete_net', 'unquoted_date'])
def test_recorded_compiler_keeps_metric_labels_and_exact_context_dates(mutation):
    path = os.getenv('ADA_RETAINED_PLAN_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_RETAINED_PLAN_DIAGNOSTIC to the private selected-plan checkpoint.')
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    result = PipelineResult.model_validate_json(Path(path).read_bytes())
    before = result.model_dump(include={'document', 'observations', 'insights', 'analysis_results'})
    plan = retained.compile_retained_analysis(result)
    target = next(s for s in plan.slides if s.slide_type == 'analysis'
                  and 'Trade receivables, net' in s.message)
    assert '2024-10-31' in target.message
    if mutation == 'incomplete_net':
        target.message += ' Net declined overall.'
    elif mutation == 'unquoted_date':
        target.message = target.message.replace('2024-10-31', '2024-10-30')
    if mutation:
        with pytest.raises(ValueError, match='incomplete net movement|unsupported numeric'):
            PresentationPlanValidator().validate(plan, result)
    else:
        PresentationPlanValidator().validate(plan, result)
    assert result.model_dump(include=set(before)) == before
    assert not review_complete(result)
