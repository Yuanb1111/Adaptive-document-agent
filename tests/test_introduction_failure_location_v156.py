"""The failure stage and page locators must not be confused with resume position."""
import json
from contextlib import ExitStack
from time import perf_counter

from adaptive_document_agent.agent.introduction_checkpoint import failed_introduction_result
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.export import export_json
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from adaptive_document_agent.ui.processing_progress import ProcessingProgress
from tests.test_complete_summary_reading import source


def test_checkpoint_exports_actual_reading_failure_and_updates_progress_identity():
    result = source(13)
    result.validation_warnings.append(ValidationIssue(code='company_introduction_summary_audit',
        severity='info', stage='presentation', message=json.dumps({
            'source_blocks': [{'id': 'a', 'page': 12}, {'id': 'b', 'page': 13}],
            'read_audits': [{'block_ids': ['a', 'b'], 'failure_kind': 'format',
                             'error': 'Format recovery failed'}]})))
    class Prepared:
        def copy_audit(self, current): pass
    class Gateway:
        usage = []
    progress = ProcessingProgress(None)
    progress.update('Generating analysis candidates')
    failed_introduction_result(Prepared(), result, Gateway(), ExitStack(), {}, {}, perf_counter(),
        progress.update, before_scoring=True, failure=LLMResponseError('Format recovery failed'))
    assert result.failed_stage == 'introduction_reading'
    assert result.retry_from == 'candidate_scoring'
    assert result.failure_details['source_pages'] == [12, 13]
    assert result.failure_details['operation'] == 'SummaryReadBatch'
    assert progress.stage_id == 'introduction_reading'
    assert '12, 13' in progress.label
    assert json.loads(export_json(result))['failed_stage'] == 'introduction_reading'


def test_old_results_and_non_json_audits_keep_a_safe_generic_failure():
    from adaptive_document_agent.agent.introduction_failure import introduction_failure_details
    result = source(1)
    result.validation_warnings.append(ValidationIssue(code='company_introduction_summary_audit',
        severity='info', stage='presentation', message='Legacy diagnostics'))
    stage, details = introduction_failure_details(result, ValueError('Rejected evidence'))
    assert stage == 'introduction' and details['source_pages'] == []


def test_editorial_no_progress_reports_the_actual_operation_and_source_pages():
    from adaptive_document_agent.agent.introduction_failure import introduction_failure_details
    result = source(13)
    result.validation_warnings.append(ValidationIssue(code='company_introduction_summary_audit',
        severity='info', stage='presentation', message=json.dumps({
            'plan_audits': [dict(compact_semantic_review={'parts': [dict(part_id='condition', accepted=False)]}),
                            dict(revision_failed=True, errors=['Content repair repeated the rejected draft'])],
            'parts': [dict(id='condition', source_page=10)]})))
    stage, details = introduction_failure_details(result, ValueError('No progress'))
    assert stage == 'introduction_content_repair'
    assert details['operation'] == 'SummarySynthesisRevision' and details['source_pages'] == [10]
