"""Keep structured retry evidence in the diagnostic result, not audience prose."""
import json

import pytest

from adaptive_document_agent.agent.report_generator import ReportGenerator
from adaptive_document_agent.models import DocumentProfile, ReportPlan, ReportSection, ValidationIssue


@pytest.mark.parametrize('with_quality_section', [False, True])
def test_structured_receipts_stay_in_diagnostics_and_plain_warnings_remain_visible(with_quality_section):
    plan = ReportPlan(sections=[ReportSection(title='Data Quality and Limitations',
        purpose='Source limits')] if with_quality_section else [])
    codes = ['executive_brief_review_checkpoint', 'executive_brief_retry_feedback',
             'presentation_retained_analysis_selection', 'source_integration_review']
    issues = [ValidationIssue(code=code, severity='info', stage='report',
        message=json.dumps({'environment_key':'internal hash', 'candidate':{'text':'Unverified draft'}}))
        for code in codes]
    issues.extend([ValidationIssue(code='extraction_limit', severity='warning', stage='extraction',
        message='[Table 1] Units could not be verified.'),
        ValidationIssue(code='presentation_ratio_definition', severity='info', stage='presentation',
                        message=json.dumps({'before': 'Unverified draft'}))])
    before = [issue.model_dump_json() for issue in issues]
    rendered = ReportGenerator().generate(DocumentProfile(), plan, [], issues)
    assert 'environment_key' not in rendered and 'Unverified draft' not in rendered
    assert '[Table 1] Units could not be verified.' in rendered
    assert 'explicit source definition' in rendered
    assert [issue.model_dump_json() for issue in issues] == before


def test_receipts_alone_do_not_create_an_empty_warnings_section():
    issue = ValidationIssue(code='executive_brief_review_checkpoint', severity='info',
                            stage='report', message='{"checked":{"0":[]},"pending":[]}')
    rendered = ReportGenerator().generate(DocumentProfile(), ReportPlan(), [], [issue])
    assert 'Validation Warnings' not in rendered and 'checked' not in rendered


@pytest.mark.parametrize('severity', ['warning', 'error'])
def test_structured_source_limitation_remains_visible(severity):
    detail = json.dumps({'page': 12, 'error': 'Conflicting units'})
    issue = ValidationIssue(code='source_unit_conflict', stage='extraction',
                            severity=severity, message=detail)
    rendered = ReportGenerator().generate(DocumentProfile(), ReportPlan(), [], [issue])
    assert f'[{severity.upper()}] {detail}' in rendered


def test_structured_withholding_shows_the_limitation_and_keeps_draft_in_diagnostics():
    draft = json.dumps({'slide_id': 'closing', 'statement': 'Rejected conclusion'})
    issues = [ValidationIssue(code='presentation_closing_claim_withheld', stage='presentation',
                              severity='warning', message=draft),
              ValidationIssue(code='presentation_caveat_note_review', stage='presentation',
                              severity='warning', message='[Table 1] A source caveat needs review.')]
    rendered = ReportGenerator().generate(DocumentProfile(), ReportPlan(), [], issues)
    assert 'closing statement was withheld' in rendered
    assert '[Table 1] A source caveat needs review.' in rendered
    assert 'Rejected conclusion' not in rendered and issues[0].message == draft
